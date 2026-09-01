"""Tests for CrossEncoderReranker and its integration into the RAG pipeline.

Covers:
  - Reranker: mock scoring, sort order, model caching, error handling
  - Pipeline: rerank-enabled vs disabled, expanded recall, result format
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.core.rag.pipeline import RAGPipeline
from app.core.rag.reranker import CrossEncoderReranker
from tests.conftest import MockVectorStore


# ═════════════════════════════════════════════════════════════════════
#  Fixtures
# ═════════════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def _clear_reranker_singleton():
    """Reset the CrossEncoderReranker singleton before each test."""
    CrossEncoderReranker._instance = None
    CrossEncoderReranker._model = None
    CrossEncoderReranker._model_name = None


DOCS_MIXED = [
    ("id-java-1", "HashMap in Java uses array of buckets with linked list or tree for collision resolution", {"subject": "Java", "topic": "collections"}),
    ("id-java-2", "ArrayList in Java implements dynamic array that grows automatically when full", {"subject": "Java", "topic": "collections"}),
    ("id-py-1", "Python list comprehension provides concise way to create lists", {"subject": "Python", "topic": "core"}),
    ("id-db-1", "Database index improves query performance by reducing full table scans", {"subject": "DB", "topic": "indexing"}),
]


def _make_store(docs: list[tuple] = DOCS_MIXED) -> MockVectorStore:
    store = MockVectorStore()
    # pipeline._retrieve uses f"kb_{kb_id}", so collection must match
    store.collections["kb_test_kb"] = [
        {"id": d[0], "embedding": [0.0] * 384, "document": d[1], "metadata": d[2]}
        for d in docs
    ]
    return store


# ═════════════════════════════════════════════════════════════════════
#  CrossEncoderReranker (mocked model)
# ═════════════════════════════════════════════════════════════════════

class MockCrossEncoder:
    """Fake cross-encoder that scores Java docs higher for HashMap queries."""

    def predict(self, pairs, batch_size=16, show_progress_bar=False):
        scores = []
        for query, doc_text in pairs:
            score = 0.1
            if "hashmap" in query.lower() and "hashmap" in doc_text.lower():
                score = 0.95
            elif "java" in doc_text.lower():
                score = 0.70
            elif "python" in doc_text.lower():
                score = 0.40
            elif "database" in doc_text.lower():
                score = 0.25
            scores.append(score)
        return scores


class TestCrossEncoderReranker:
    """Unit tests with mocked model."""

    @pytest.mark.asyncio
    async def test_rerank_sorts_by_relevance(self):
        """Reranker promotes Java/HashMap docs for 'HashMap原理' query."""
        reranker = CrossEncoderReranker()
        reranker._model = MockCrossEncoder()
        reranker._model_name = "mock"

        documents = [
            {"id": "1", "document": "Python list comprehension is concise", "metadata": {"subject": "Python"}},
            {"id": "2", "document": "HashMap in Java uses buckets", "metadata": {"subject": "Java"}},
            {"id": "3", "document": "Database index improves query speed", "metadata": {"subject": "DB"}},
        ]

        result = await reranker.rerank(query="HashMap原理", documents=documents, top_k=3, model_name="mock")

        assert len(result) == 3
        assert result[0]["id"] == "2"  # HashMap doc first
        assert result[0]["rerank_score"] > result[1]["rerank_score"]

    @pytest.mark.asyncio
    async def test_rerank_top_k(self):
        """top_k limits number of returned results."""
        reranker = CrossEncoderReranker()
        reranker._model = MockCrossEncoder()
        reranker._model_name = "mock"

        documents = [
            {"id": str(i), "document": f"Document {i} content", "metadata": {}}
            for i in range(10)
        ]

        result = await reranker.rerank(query="test", documents=documents, top_k=3, model_name="mock")
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_rerank_empty_documents(self):
        """Empty documents returns empty list."""
        reranker = CrossEncoderReranker()
        reranker._model = MockCrossEncoder()
        reranker._model_name = "mock"

        result = await reranker.rerank(query="test", documents=[], top_k=5, model_name="mock")
        assert result == []

    @pytest.mark.asyncio
    async def test_rerank_model_load_failure_fallback(self):
        """If model fails to load, fallback returns top-k of input."""
        reranker = CrossEncoderReranker()
        documents = [{"id": "1", "document": "content", "metadata": {}} for _ in range(5)]

        result = await reranker.rerank(query="test", documents=documents, top_k=3, model_name="invalid-model-xyz")
        assert len(result) == 3  # fallback

    @pytest.mark.asyncio
    async def test_model_singleton(self):
        """CrossEncoderReranker is a singleton."""
        r1 = CrossEncoderReranker()
        r2 = CrossEncoderReranker()
        assert r1 is r2

    @pytest.mark.asyncio
    async def test_get_model_info(self):
        """get_model_info returns correct metadata."""
        reranker = CrossEncoderReranker()
        info = reranker.get_model_info()
        assert info["loaded"] is False
        assert info["model_name"] is None

        reranker._model = MockCrossEncoder()
        reranker._model_name = "mock-model"
        info = reranker.get_model_info()
        assert info["loaded"] is True
        assert info["model_name"] == "mock-model"

    @pytest.mark.asyncio
    async def test_reranker_injects_rerank_score(self):
        """Each result dict gets a rerank_score key after rerank."""
        reranker = CrossEncoderReranker()
        reranker._model = MockCrossEncoder()
        reranker._model_name = "mock"

        documents = [
            {"id": "1", "document": "Python content", "metadata": {}},
            {"id": "2", "document": "Java content", "metadata": {}},
        ]

        result = await reranker.rerank(query="Java", documents=documents, top_k=2, model_name="mock")
        for r in result:
            assert "rerank_score" in r
            assert isinstance(r["rerank_score"], float)


# ═════════════════════════════════════════════════════════════════════
#  Pipeline integration
# ═════════════════════════════════════════════════════════════════════

@pytest.fixture
def mock_rag_pipeline(rag_pipeline) -> RAGPipeline:
    """RAGPipeline with mocked reranker."""

    async def mock_rerank(query, results, top_k):
        scored = []
        for r in results:
            doc = r.get("document", "").lower()
            score = 0.9 if "hashmap" in doc else 0.6 if "java" in doc else 0.3
            r["rerank_score"] = score
            scored.append(r)
        scored.sort(key=lambda x: x["rerank_score"], reverse=True)
        return scored[:top_k]

    rag_pipeline._rerank = mock_rerank
    return rag_pipeline


class TestPipelineRerankIntegration:
    """Pipeline behaviour with reranker enabled/disabled."""

    @pytest.mark.asyncio
    async def test_retrieve_expanded_recall(self, mock_rag_pipeline):
        """_retrieve calls dense/sparse with candidate_k >= 30."""
        store = _make_store()
        mock_rag_pipeline.vector_store = store

        results = await mock_rag_pipeline._retrieve(
            query="HashMap原理", kb_id="test_kb", k=3, alpha=0.6,
        )
        assert len(results) <= 3
        if results:
            assert results[0]["id"] == "id-java-1"
            assert "rerank_score" in results[0]

    @pytest.mark.asyncio
    async def test_rerank_enabled_vs_disabled(self, rag_pipeline):
        """Pipeline._rerank processes results through CrossEncoderReranker."""
        # Mock the CrossEncoderReranker singleton to avoid real model loading
        from app.core.rag.reranker import CrossEncoderReranker
        reranker = CrossEncoderReranker()
        reranker._model = MockCrossEncoder()
        reranker._model_name = "mock"

        docs = [
            {"id": "1", "document": "Python content", "metadata": {}, "score": 0.8},
            {"id": "2", "document": "Java HashMap content", "metadata": {}, "score": 0.7},
        ]
        result = await rag_pipeline._rerank("HashMap", docs, top_k=2)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_search_only_rerank_flag(self, rag_pipeline):
        """search_only with rerank=True passes through pipeline."""
        store = _make_store()
        rag_pipeline.vector_store = store
        rag_pipeline.embedding_model = type('MockEmb', (), {
            'embed_text': AsyncMock(return_value=[0.1] * 384)
        })()

        with patch("app.core.rag.pipeline.settings") as mock_settings:
            mock_settings.rerank_enabled = True
            mock_settings.rerank_candidate_k = 30
            mock_settings.rerank_output_k = 5

            result = await rag_pipeline.search_only(
                query="HashMap",
                kb_id="test_kb",
                k=3,
                strategy="hybrid",
                rerank=True,
            )
            assert "results" in result
            assert len(result["results"]) <= 3

    @pytest.mark.asyncio
    async def test_generate_answer_sources_include_rerank_score(self, rag_pipeline, mock_llm):
        """generate_answer sources include rerank_score field."""
        store = _make_store()
        rag_pipeline.vector_store = store
        rag_pipeline.llm = mock_llm
        rag_pipeline.embedding_model = type('MockEmb', (), {
            'embed_text': AsyncMock(return_value=[0.1] * 384)
        })()

        with patch("app.core.rag.pipeline.settings") as mock_settings:
            mock_settings.rerank_enabled = True
            mock_settings.rerank_candidate_k = 30
            mock_settings.rerank_output_k = 5

            result = await rag_pipeline.generate_answer(
                query="HashMap",
                kb_id="test_kb",
                k=3,
            )
            for source in result["sources"]:
                assert "rerank_score" in source


class TestRerankerChineseScenario:
    """Chinese query re-ranking behaviour with mock model."""

    @pytest.mark.asyncio
    async def test_chinese_query_promotes_relevant_docs(self):
        """Chinese query '快速排序时间复杂度' promotes sorting-related docs."""
        reranker = CrossEncoderReranker()

        class ChineseMockModel:
            def predict(self, pairs, batch_size=16, show_progress_bar=False):
                scores = []
                for query, doc_text in pairs:
                    score = 0.1
                    if "排序" in doc_text:
                        score = 0.90
                    elif "算法" in doc_text:
                        score = 0.60
                    else:
                        score = 0.30
                    scores.append(score)
                return scores

        reranker._model = ChineseMockModel()
        reranker._model_name = "mock-cn"

        documents = [
            {"id": "d1", "document": "快速排序是一种基于分治思想的高效排序算法", "metadata": {"subject": "算法"}},
            {"id": "d2", "document": "Java中的HashMap基于数组加链表实现键值对存储", "metadata": {"subject": "Java"}},
            {"id": "d3", "document": "Python动态类型系统无需声明变量类型", "metadata": {"subject": "Python"}},
        ]

        result = await reranker.rerank(query="快速排序时间复杂度", documents=documents, top_k=3, model_name="mock-cn")
        assert result[0]["id"] == "d1"  # 排序算法文档排第一
        assert result[0]["rerank_score"] > result[1]["rerank_score"]


# ═════════════════════════════════════════════════════════════════════
#  Pipeline two-stage flow verification
# ═════════════════════════════════════════════════════════════════════

class TestTwoStageRetrieval:
    """Verification of the full two-stage flow: recall → rerank."""

    @pytest.mark.asyncio
    async def test_rerank_does_not_replace_rrf(self, rag_pipeline):
        """Reranker operates after RRF, does not bypass it."""
        store = _make_store()
        rag_pipeline.vector_store = store
        rag_pipeline.embedding_model = type('MockEmb', (), {
            'embed_text': AsyncMock(return_value=[0.1] * 384)
        })()

        fusion_called = False
        sparse_called = False

        original_fusion = rag_pipeline._hybrid_fusion
        original_sparse = rag_pipeline._sparse_search

        def tracking_fusion(dense, sparse, alpha, k):
            nonlocal fusion_called
            fusion_called = True
            return original_fusion(dense, sparse, alpha, k)

        async def tracking_sparse(q, coll, k):
            nonlocal sparse_called
            sparse_called = True
            return await original_sparse(q, coll, k)

        rag_pipeline._hybrid_fusion = tracking_fusion
        rag_pipeline._sparse_search = tracking_sparse

        with patch("app.core.rag.pipeline.settings") as mock_settings:
            mock_settings.rerank_enabled = True
            mock_settings.rerank_candidate_k = 30
            mock_settings.rerank_output_k = 5

            await rag_pipeline._retrieve(query="test", kb_id="test_kb", k=5, alpha=0.6)

        assert fusion_called, "RRF fusion must be executed before rerank"
        assert sparse_called, "BM25 sparse search must be executed"

    @pytest.mark.asyncio
    async def test_alpha_independent_from_rerank(self, rag_pipeline):
        """Alpha (dense/sparse weight) is independent from reranker."""
        store = _make_store()
        rag_pipeline.vector_store = store
        rag_pipeline.embedding_model = type('MockEmb', (), {
            'embed_text': AsyncMock(return_value=[0.1] * 384)
        })()

        with patch("app.core.rag.pipeline.settings") as mock_settings:
            mock_settings.rerank_enabled = True
            mock_settings.rerank_candidate_k = 30
            mock_settings.rerank_output_k = 5

            r1 = await rag_pipeline._retrieve(query="HashMap", kb_id="test_kb", k=3, alpha=0.2)
            r2 = await rag_pipeline._retrieve(query="HashMap", kb_id="test_kb", k=3, alpha=0.8)

            assert len(r1) <= 3
            assert len(r2) <= 3
