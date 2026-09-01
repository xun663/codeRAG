"""Tests for the RAG pipeline (app/core/rag/pipeline.py).

Covers:
  - _hybrid_fusion: weighted reciprocal rank fusion
  - _build_prompt: system/user prompt construction
  - _format_answer: citation footer logic
  - search_only: dense/sparse/hybrid strategies
  - _retrieve: basic + multi-query fusion
  - generate_answer: full generation flow
  - generate_stream: SSE event streaming
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch, PropertyMock

import pytest

from app.core.rag.pipeline import RAGPipeline
from app.core.rag.intent_classifier import Intent
from app.core.rag.query_standardizer import StandardizationResult


# ═════════════════════════════════════════════════════════════════════
#  Helper factories
# ═════════════════════════════════════════════════════════════════════

def make_chunk(
    chunk_id: str,
    score: float = 0.8,
    document: str = "Some content.",
    doc_title: str = "Test Doc",
    chunk_type: str = "text",
    topic: str = "",
) -> dict:
    return {
        "id": chunk_id,
        "score": score,
        "document": document,
        "metadata": {
            "doc_title": doc_title,
            "chunk_type": chunk_type,
            "topic": topic,
        },
    }


# ═════════════════════════════════════════════════════════════════════
#  _hybrid_fusion
# ═════════════════════════════════════════════════════════════════════

class TestHybridFusion:
    """Weighted reciprocal rank fusion — unit-tested directly."""

    def test_only_dense_results(self, rag_pipeline: RAGPipeline):
        dense = [make_chunk("a", 0.9), make_chunk("b", 0.8)]
        result = rag_pipeline._hybrid_fusion(dense, [], alpha=0.6, k=5)
        assert len(result) == 2
        assert result[0]["id"] == "a"
        assert result[1]["id"] == "b"

    def test_only_sparse_results(self, rag_pipeline: RAGPipeline):
        sparse = [make_chunk("x", 0.7)]
        result = rag_pipeline._hybrid_fusion([], sparse, alpha=0.6, k=5)
        assert len(result) == 1
        assert result[0]["id"] == "x"

    def test_both_empty(self, rag_pipeline: RAGPipeline):
        result = rag_pipeline._hybrid_fusion([], [], alpha=0.6, k=5)
        assert result == []

    def test_fusion_ranking(self, rag_pipeline: RAGPipeline):
        """Dense and sparse share one overlapping item; fusion ranks correctly."""
        dense = [
            make_chunk("a", 0.9, document="Alpha"),
            make_chunk("b", 0.8, document="Beta"),
        ]
        sparse = [
            make_chunk("b", 0.7, document="Beta"),   # overlap
            make_chunk("c", 0.6, document="Gamma"),
        ]
        result = rag_pipeline._hybrid_fusion(dense, sparse, alpha=0.6, k=5)
        assert len(result) == 3
        # a: dense RRF only: 0.6 * 1/1 = 0.6
        # b: dense RRF (0.6 * 1/2) + sparse RRF (0.4 * 1/1) = 0.3 + 0.4 = 0.7
        # c: sparse RRF only: 0.4 * 1/2 = 0.2
        assert result[0]["id"] == "b"  # 0.7 (boosted by two lists)
        assert result[1]["id"] == "a"  # 0.6
        assert result[2]["id"] == "c"  # 0.2

    def test_k_truncation(self, rag_pipeline: RAGPipeline):
        """k parameter limits the number of returned results."""
        dense = [make_chunk(f"chunk-{i}", 0.9 - i * 0.01) for i in range(10)]
        result = rag_pipeline._hybrid_fusion(dense, [], alpha=0.6, k=3)
        assert len(result) == 3

    def test_alpha_zero_pure_sparse(self, rag_pipeline: RAGPipeline):
        dense = [make_chunk("a", 0.9), make_chunk("b", 0.8)]
        sparse = [make_chunk("c", 0.7)]
        result = rag_pipeline._hybrid_fusion(dense, sparse, alpha=0.0, k=5)
        # alpha=0 gives all weight to sparse
        assert len(result) == 3

    def test_alpha_one_pure_dense(self, rag_pipeline: RAGPipeline):
        dense = [make_chunk("a", 0.9)]
        sparse = [make_chunk("b", 0.7)]
        result = rag_pipeline._hybrid_fusion(dense, sparse, alpha=1.0, k=5)
        assert len(result) == 2

    def test_identical_items_deduped(self, rag_pipeline: RAGPipeline):
        """Same ID in both lists gets merged, keeping the dense version's data."""
        dense = [make_chunk("a", 0.9, document="From dense")]
        sparse = [make_chunk("a", 0.6, document="From sparse")]
        result = rag_pipeline._hybrid_fusion(dense, sparse, alpha=0.6, k=5)
        assert len(result) == 1
        assert result[0]["document"] == "From dense"  # Dense takes priority for document


# ═════════════════════════════════════════════════════════════════════
#  _build_prompt
# ═════════════════════════════════════════════════════════════════════

class TestBuildPrompt:
    """System and user prompt construction."""

    def test_basic_prompt(self, rag_pipeline: RAGPipeline, sample_chunks: list[dict]):
        system_prompt, user_prompt = rag_pipeline._build_prompt(
            "What is a tuple?", sample_chunks
        )
        assert "programming learning assistant" in system_prompt
        assert "What is a tuple?" in user_prompt
        assert "Python tuples are immutable" in user_prompt
        assert "[source:1]" in user_prompt

    def test_no_context(self, rag_pipeline: RAGPipeline):
        system_prompt, user_prompt = rag_pipeline._build_prompt("Hello", [])
        assert "Knowledge Base Context" in user_prompt
        # Empty context -> blank line between --- markers
        assert "---\n\n---" in user_prompt

    def test_with_history(self, rag_pipeline: RAGPipeline, conversation_history: list[dict]):
        _, user_prompt = rag_pipeline._build_prompt(
            "Explain further", [], conversation_history
        )
        assert "Conversation History" in user_prompt
        assert "User: What is a tuple" in user_prompt
        assert "Assistant: A tuple is" in user_prompt

    def test_history_truncation(self, rag_pipeline: RAGPipeline):
        """Only last 6 messages are included."""
        long_history = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i}"}
                        for i in range(20)]
        _, user_prompt = rag_pipeline._build_prompt("test", [], long_history)
        # Should only have messages 14-19 (last 6)
        assert "msg 13" not in user_prompt
        assert "msg 14" in user_prompt

    def test_source_limit_five(self, rag_pipeline: RAGPipeline):
        """Only first 5 chunks are included in context."""
        chunks = [make_chunk(f"c{i}", document=f"Content {i}") for i in range(10)]
        _, user_prompt = rag_pipeline._build_prompt("test", chunks)
        assert "Content 0" in user_prompt
        assert "Content 4" in user_prompt
        assert "Content 5" not in user_prompt


# ═════════════════════════════════════════════════════════════════════
#  _format_answer
# ═════════════════════════════════════════════════════════════════════

class TestFormatAnswer:
    """Answer formatting with citation footers."""

    def test_existing_footer_unchanged(self, rag_pipeline: RAGPipeline):
        answer = "This is the answer.\n\n---\n📚 **参考来源**"
        result = rag_pipeline._format_answer(answer, [])
        assert result == answer

    def test_no_chunks_adds_model_footer(self, rag_pipeline: RAGPipeline):
        answer = "This is a model-generated answer."
        result = rag_pipeline._format_answer(answer, [])
        assert "🤖" in result
        assert "生成说明" in result
        assert result.startswith(answer.rstrip())

    def test_with_chunks_adds_kb_footer(self, rag_pipeline: RAGPipeline, sample_chunks: list[dict]):
        answer = "Tuples are immutable."
        result = rag_pipeline._format_answer(answer, sample_chunks)
        assert "📚" in result
        assert "参考来源" in result
        assert "Python Docs" in result
        assert result.startswith(answer.rstrip())

    def test_footer_includes_content_preview(self, rag_pipeline: RAGPipeline, sample_chunks: list[dict]):
        answer = "Answer here."
        result = rag_pipeline._format_answer(answer, sample_chunks)
        assert "引用原文" in result
        assert "Python tuples are immutable" in result

    def test_max_three_sources_in_footer(self, rag_pipeline: RAGPipeline):
        chunks = [make_chunk(f"c{i}", document=f"Doc {i}") for i in range(10)]
        answer = "Many sources."
        result = rag_pipeline._format_answer(answer, chunks)
        # Count occurrences of doc_title references
        assert result.count("Test Doc") <= 3

    def test_existing_robot_footer(self, rag_pipeline: RAGPipeline):
        answer = "Done.\n\n---\n🤖 **模型生成**"
        result = rag_pipeline._format_answer(answer, [])
        assert result == answer  # Unchanged because it already has 🤖 footer

    def test_existing_mixed_footer(self, rag_pipeline: RAGPipeline):
        answer = "Done.\n\n---\n🔀 **内容说明**"
        result = rag_pipeline._format_answer(answer, [])
        assert "🔀" in result


# ═════════════════════════════════════════════════════════════════════
#  search_only
# ═════════════════════════════════════════════════════════════════════

class TestSearchOnly:
    """Search without generation."""

    @pytest.mark.asyncio
    async def test_dense_strategy(self, rag_pipeline: RAGPipeline):
        # Pre-populate some data
        await rag_pipeline.vector_store.create_collection("kb_test")
        await rag_pipeline.vector_store.add_vectors(
            collection_name="kb_test",
            ids=["c1", "c2"],
            embeddings=[[0.1] * 384, [0.2] * 384],
            documents=["Doc 1", "Doc 2"],
            metadatas=[{"doc_title": "A"}, {"doc_title": "B"}],
        )

        result = await rag_pipeline.search_only(
            query="test query",
            kb_id="test",
            k=5,
            strategy="dense",
        )
        assert result["query"] == "test query"
        assert len(result["results"]) == 2
        assert "chunk_id" in result["results"][0]
        assert "score" in result["results"][0]
        assert "latency_ms" in result
        assert result["total_found"] == 2

    @pytest.mark.asyncio
    async def test_sparse_strategy_empty(self, rag_pipeline: RAGPipeline):
        """Sparse search is a placeholder that returns empty."""
        result = await rag_pipeline.search_only(
            query="test", kb_id="test", k=5, strategy="sparse"
        )
        assert len(result["results"]) == 0
        assert result["total_found"] == 0

    @pytest.mark.asyncio
    async def test_hybrid_strategy(self, rag_pipeline: RAGPipeline):
        await rag_pipeline.vector_store.create_collection("kb_hybrid")
        await rag_pipeline.vector_store.add_vectors(
            collection_name="kb_hybrid",
            ids=["h1"],
            embeddings=[[0.15] * 384],
            documents=["Hybrid doc"],
            metadatas=[{"doc_title": "Hybrid"}],
        )
        result = await rag_pipeline.search_only(
            query="hybrid query", kb_id="hybrid", k=5, strategy="hybrid"
        )
        assert len(result["results"]) >= 1

    @pytest.mark.asyncio
    async def test_without_kb_id(self, rag_pipeline: RAGPipeline):
        """Without a kb_id, collection defaults to 'default'."""
        result = await rag_pipeline.search_only(
            query="no kb", kb_id=None, k=5, strategy="dense"
        )
        assert isinstance(result, dict)
        assert "results" in result

    @pytest.mark.asyncio
    async def test_k_truncation(self, rag_pipeline: RAGPipeline):
        await rag_pipeline.vector_store.create_collection("kb_trunc")
        await rag_pipeline.vector_store.add_vectors(
            collection_name="kb_trunc",
            ids=[f"c{i}" for i in range(10)],
            embeddings=[[0.1 * i] * 384 for i in range(10)],
            documents=[f"Doc {i}" for i in range(10)],
            metadatas=[{"doc_title": f"D{i}"} for i in range(10)],
        )
        result = await rag_pipeline.search_only(
            query="test", kb_id="trunc", k=3, strategy="dense"
        )
        assert len(result["results"]) == 3


# ═════════════════════════════════════════════════════════════════════
#  _retrieve
# ═════════════════════════════════════════════════════════════════════

class TestRetrieve:
    """Internal retrieval with optional multi-query fusion."""

    @pytest.mark.asyncio
    async def test_basic_retrieve(self, rag_pipeline: RAGPipeline):
        await rag_pipeline.vector_store.create_collection("kb_ret")
        await rag_pipeline.vector_store.add_vectors(
            collection_name="kb_ret",
            ids=["r1", "r2", "r3"],
            embeddings=[[0.01] * 384, [0.02] * 384, [0.03] * 384],
            documents=["Retrieved 1", "Retrieved 2", "Retrieved 3"],
            metadatas=[{"doc_title": "R1"}, {"doc_title": "R2"}, {"doc_title": "R3"}],
        )
        results = await rag_pipeline._retrieve(
            query="test query", kb_id="ret", k=2, alpha=0.6
        )
        assert len(results) == 2
        assert all(isinstance(r, dict) for r in results)

    @pytest.mark.asyncio
    async def test_with_sub_queries(self, rag_pipeline: RAGPipeline):
        """Multi-query fusion merges results from sub-queries."""
        await rag_pipeline.vector_store.create_collection("kb_sub")
        await rag_pipeline.vector_store.add_vectors(
            collection_name="kb_sub",
            ids=["s1", "s2", "s3"],
            embeddings=[[0.0] * 384, [0.1] * 384, [0.2] * 384],
            documents=["Sub 1", "Sub 2", "Sub 3"],
            metadatas=[{"doc_title": "S1"}, {"doc_title": "S2"}, {"doc_title": "S3"}],
        )
        results = await rag_pipeline._retrieve(
            query="main query",
            kb_id="sub",
            k=5,
            alpha=0.6,
            sub_queries=["sub query one", "sub query two"],
        )
        # Should have merged results
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_sub_queries_dedup(self, rag_pipeline: RAGPipeline):
        """Duplicate chunk IDs from sub-queries should be deduplicated (highest score wins)."""
        await rag_pipeline.vector_store.create_collection("kb_dedup")
        await rag_pipeline.vector_store.add_vectors(
            collection_name="kb_dedup",
            ids=["d1", "d2"],
            embeddings=[[0.0] * 384, [0.1] * 384],
            documents=["Dup 1", "Dup 2"],
            metadatas=[{"doc_title": "D1"}, {"doc_title": "D2"}],
        )
        results = await rag_pipeline._retrieve(
            query="q", kb_id="dedup", k=10, alpha=0.6,
            sub_queries=["sub"],
        )
        # Check no duplicate IDs
        ids = [r["id"] for r in results]
        assert len(ids) == len(set(ids))

    @pytest.mark.asyncio
    async def test_max_three_sub_queries(self, rag_pipeline: RAGPipeline):
        """Only the first 3 sub-queries should be processed."""
        many_subs = [f"sub query {i}" for i in range(10)]
        await rag_pipeline.vector_store.create_collection("kb_maxsub")
        await rag_pipeline.vector_store.add_vectors(
            collection_name="kb_maxsub",
            ids=["m1"],
            embeddings=[[0.0] * 384],
            documents=["Max sub"],
            metadatas=[{"doc_title": "M1"}],
        )
        results = await rag_pipeline._retrieve(
            query="q", kb_id="maxsub", k=5, alpha=0.6, sub_queries=many_subs
        )
        assert len(results) >= 1


# ═════════════════════════════════════════════════════════════════════
#  generate_answer
# ═════════════════════════════════════════════════════════════════════

class TestGenerateAnswer:
    """Full generate_answer flow — patches _retrieve and standardizer."""

    @pytest.fixture
    def std_result(self) -> StandardizationResult:
        return StandardizationResult(
            original="What is a tuple?",
            cleaned="What is a tuple?",
            rewritten="Python tuple definition and usage",
            expanded_keywords=["immutable", "sequence"],
            sub_queries=["tuple vs list", "tuple methods"],
            used_llm=True,
        )

    @pytest.mark.asyncio
    async def test_generate_answer_with_knowledge(
        self, rag_pipeline: RAGPipeline, std_result: StandardizationResult,
        sample_chunks: list[dict], mock_llm,
    ):
        with (
            patch.object(rag_pipeline, "_retrieve", new=AsyncMock(return_value=sample_chunks)),
            patch("app.core.rag.pipeline.get_query_standardizer") as mock_get_std,
        ):
            mock_std = AsyncMock()
            mock_std.process = AsyncMock(return_value=std_result)
            mock_get_std.return_value = mock_std

            result = await rag_pipeline.generate_answer(
                query="What is a tuple?",
                kb_id="test_kb",
                conversation_history=None,
                k=5,
                alpha=0.6,
                intent=Intent.KNOWLEDGE,
            )

        assert "answer" in result
        assert "sources" in result
        assert "latency_ms" in result
        assert "prompt_tokens" in result
        assert "completion_tokens" in result
        assert "standardized_query" in result
        assert result["standardized_query"] == "Python tuple definition and usage"
        assert len(result["sources"]) == 2
        # Answer is formatted with KB citation footer
        assert mock_llm._response in result["answer"]
        assert "📚" in result["answer"]

    @pytest.mark.asyncio
    async def test_generate_answer_chunks_assigned_to_result(
        self, rag_pipeline: RAGPipeline, sample_chunks: list[dict],
    ):
        std_result = StandardizationResult(
            original="test", cleaned="test", rewritten="test",
        )
        with (
            patch.object(rag_pipeline, "_retrieve", new=AsyncMock(return_value=sample_chunks)),
            patch("app.core.rag.pipeline.get_query_standardizer") as mock_get_std,
        ):
            mock_std = AsyncMock()
            mock_std.process = AsyncMock(return_value=std_result)
            mock_get_std.return_value = mock_std

            result = await rag_pipeline.generate_answer(
                query="test", kb_id="test_kb",
            )
        sources = result["sources"]
        assert sources[0]["chunk_id"] == "chunk-001"
        assert sources[0]["doc_title"] == "Python Docs"
        assert sources[0]["chunk_type"] == "text"

    @pytest.mark.asyncio
    async def test_generate_answer_greeting_intent(
        self, rag_pipeline: RAGPipeline,
    ):
        """GREETING intent should skip retrieval entirely."""
        std_result = StandardizationResult(
            original="hello", cleaned="hello",
        )
        with (
            patch.object(rag_pipeline, "_retrieve", new=AsyncMock()) as mock_retrieve,
            patch("app.core.rag.pipeline.get_query_standardizer") as mock_get_std,
        ):
            mock_std = AsyncMock()
            mock_std.process = AsyncMock(return_value=std_result)
            mock_get_std.return_value = mock_std

            result = await rag_pipeline.generate_answer(
                query="hello", kb_id="test_kb", intent=Intent.GREETING,
            )
        mock_retrieve.assert_not_called()
        assert "answer" in result
        assert result["sources"] == []

    @pytest.mark.asyncio
    async def test_generate_answer_meta_intent(
        self, rag_pipeline: RAGPipeline,
    ):
        """META intent should also skip retrieval."""
        std_result = StandardizationResult(
            original="what can you do", cleaned="what can you do",
        )
        with (
            patch.object(rag_pipeline, "_retrieve", new=AsyncMock()) as mock_retrieve,
            patch("app.core.rag.pipeline.get_query_standardizer") as mock_get_std,
        ):
            mock_std = AsyncMock()
            mock_std.process = AsyncMock(return_value=std_result)
            mock_get_std.return_value = mock_std

            result = await rag_pipeline.generate_answer(
                query="what can you do", kb_id="test_kb", intent=Intent.META,
            )
        mock_retrieve.assert_not_called()

    @pytest.mark.asyncio
    async def test_generate_answer_with_history(
        self, rag_pipeline: RAGPipeline, sample_chunks: list[dict],
        conversation_history: list[dict],
    ):
        std_result = StandardizationResult(
            original="explain more", cleaned="explain more", rewritten="explain tuples in detail",
        )
        with (
            patch.object(rag_pipeline, "_retrieve", new=AsyncMock(return_value=sample_chunks)),
            patch("app.core.rag.pipeline.get_query_standardizer") as mock_get_std,
        ):
            mock_std = AsyncMock()
            mock_std.process = AsyncMock(return_value=std_result)
            mock_get_std.return_value = mock_std

            result = await rag_pipeline.generate_answer(
                query="explain more",
                kb_id="test_kb",
                conversation_history=conversation_history,
            )
        assert result["answer"] is not None

    @pytest.mark.asyncio
    async def test_citation_footer_appended(
        self, rag_pipeline: RAGPipeline, sample_chunks: list[dict],
    ):
        """Answer is formatted with KB citation footer when chunks exist."""
        std_result = StandardizationResult(
            original="test", cleaned="test", rewritten="test",
        )
        with (
            patch.object(rag_pipeline, "_retrieve", new=AsyncMock(return_value=sample_chunks)),
            patch("app.core.rag.pipeline.get_query_standardizer") as mock_get_std,
        ):
            mock_std = AsyncMock()
            mock_std.process = AsyncMock(return_value=std_result)
            mock_get_std.return_value = mock_std

            # Mock LLM to return an answer WITHOUT existing footer
            rag_pipeline.llm._response = "Tuples are immutable sequences."
            result = await rag_pipeline.generate_answer(
                query="test", kb_id="test_kb",
            )
        assert "📚" in result["answer"]
        assert "参考来源" in result["answer"]


# ═════════════════════════════════════════════════════════════════════
#  generate_stream
# ═════════════════════════════════════════════════════════════════════

class TestGenerateStream:
    """Streaming answer — yields sources, tokens, done events."""

    @pytest.mark.asyncio
    async def test_stream_events(self, rag_pipeline: RAGPipeline, sample_chunks: list[dict]):
        std_result = StandardizationResult(
            original="test", cleaned="test", rewritten="test",
        )
        with (
            patch.object(rag_pipeline, "_retrieve", new=AsyncMock(return_value=sample_chunks)),
            patch("app.core.rag.pipeline.get_query_standardizer") as mock_get_std,
        ):
            mock_std = AsyncMock()
            mock_std.process = AsyncMock(return_value=std_result)
            mock_get_std.return_value = mock_std

            events = []
            async for event in rag_pipeline.generate_stream(
                query="test", kb_id="test_kb",
            ):
                events.append(event)

        assert len(events) >= 3
        # Phase events are emitted before sources — filter them out
        non_phase = [e for e in events if e["type"] != "phase"]
        assert non_phase[0]["type"] == "sources"
        assert "sources" in non_phase[0]
        assert events[-1]["type"] == "done"
        assert "content" in events[-1]
        assert "latency_ms" in events[-1]

    @pytest.mark.asyncio
    async def test_stream_phase_events(self, rag_pipeline: RAGPipeline, sample_chunks: list[dict]):
        """Phase events are emitted before retrieval and generation."""
        std_result = StandardizationResult(
            original="test", cleaned="test", rewritten="test",
        )
        with (
            patch.object(rag_pipeline, "_retrieve", new=AsyncMock(return_value=sample_chunks)),
            patch("app.core.rag.pipeline.get_query_standardizer") as mock_get_std,
        ):
            mock_std = AsyncMock()
            mock_std.process = AsyncMock(return_value=std_result)
            mock_get_std.return_value = mock_std

            events = []
            async for event in rag_pipeline.generate_stream(
                query="test", kb_id="test_kb",
            ):
                events.append(event)

        phase_events = [e for e in events if e["type"] == "phase"]
        assert len(phase_events) >= 2
        assert phase_events[0]["phase"] == "analyzing"
        assert phase_events[1]["phase"] == "searching"

    @pytest.mark.asyncio
    async def test_stream_tokens_in_order(self, rag_pipeline: RAGPipeline, sample_chunks: list[dict]):
        std_result = StandardizationResult(
            original="test", cleaned="test", rewritten="test",
        )
        rag_pipeline.llm._response = "A B C"
        with (
            patch.object(rag_pipeline, "_retrieve", new=AsyncMock(return_value=sample_chunks)),
            patch("app.core.rag.pipeline.get_query_standardizer") as mock_get_std,
        ):
            mock_std = AsyncMock()
            mock_std.process = AsyncMock(return_value=std_result)
            mock_get_std.return_value = mock_std

            events = []
            async for event in rag_pipeline.generate_stream(
                query="test", kb_id="test_kb",
            ):
                events.append(event)

            token_events = [e for e in events if e["type"] == "token"]
            assert len(token_events) == 3  # "A", "B", "C" each with a trailing space

    @pytest.mark.asyncio
    async def test_stream_sources_before_tokens(self, rag_pipeline: RAGPipeline, sample_chunks: list[dict]):
        """Sources event must come before any token events."""
        std_result = StandardizationResult(
            original="test", cleaned="test", rewritten="test",
        )
        with (
            patch.object(rag_pipeline, "_retrieve", new=AsyncMock(return_value=sample_chunks)),
            patch("app.core.rag.pipeline.get_query_standardizer") as mock_get_std,
        ):
            mock_std = AsyncMock()
            mock_std.process = AsyncMock(return_value=std_result)
            mock_get_std.return_value = mock_std

            events = []
            async for event in rag_pipeline.generate_stream(
                query="test", kb_id="test_kb",
            ):
                events.append(event)

            # Phase events may appear before sources; skip them for this check
            non_phase = [e for e in events if e["type"] != "phase"]
            first_non_sources = next(i for i, e in enumerate(non_phase) if e["type"] != "sources")
            # All sources events should be before any non-sources event
            for i in range(first_non_sources):
                assert non_phase[i]["type"] == "sources"


# ═════════════════════════════════════════════════════════════════════
#  _rerank (placeholder)
# ═════════════════════════════════════════════════════════════════════

class TestRerank:
    """Rerank is currently a pass-through placeholder."""

    @pytest.mark.asyncio
    async def test_rerank_passthrough(self, rag_pipeline: RAGPipeline):
        chunks = [make_chunk(f"c{i}") for i in range(10)]
        result = await rag_pipeline._rerank("query", chunks, top_k=3)
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_rerank_returns_top_k(self, rag_pipeline: RAGPipeline):
        chunks = [make_chunk(f"c{i}") for i in range(5)]
        result = await rag_pipeline._rerank("query", chunks, top_k=10)
        assert len(result) == 5  # limited by input size
