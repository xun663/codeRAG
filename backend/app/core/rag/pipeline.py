"""Central RAG pipeline orchestrator."""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import AsyncGenerator

from app.config import settings
from app.embedding.factory import get_embedding_model
from app.llm.factory import get_llm_provider
from app.vector_store.factory import get_vector_store
from app.core.rag.intent_classifier import Intent
from app.core.rag.query_standardizer import get_query_standardizer

logger = logging.getLogger(__name__)


class RAGPipeline:
    """Orchestrates the full RAG pipeline: query → retrieve → generate."""

    def __init__(self):
        self.embedding_model = get_embedding_model()
        self.llm = get_llm_provider()
        self.vector_store = get_vector_store()

    async def search_only(
        self,
        query: str,
        kb_id: str | None = None,
        k: int = 5,
        strategy: str = "hybrid",
        alpha: float = 0.6,
        rerank: bool = False,
    ) -> dict:
        """Search without generation (for search/debug endpoints).

        When ``rerank=True`` and the strategy is hybrid, the pipeline expands
        recall (dense/sparse each fetch ``candidate_k``), fuses via RRF, then
        applies cross-encoder re-ranking.
        """
        start = time.monotonic()

        query_embedding = await self.embedding_model.embed_text(query)
        collection = f"kb_{kb_id}" if kb_id else None

        if strategy == "dense":
            results = await self.vector_store.search(
                collection_name=collection or "default",
                query_embedding=query_embedding,
                k=k,
            )
        elif strategy == "sparse":
            results = await self._sparse_search(query, collection or "default", k)
        else:  # hybrid
            candidate_k = max(k * 2, settings.rerank_candidate_k)
            dense_results = await self.vector_store.search(
                collection_name=collection or "default",
                query_embedding=query_embedding,
                k=candidate_k,
            )
            sparse_results = await self._sparse_search(query, collection or "default", candidate_k)
            results = self._hybrid_fusion(dense_results, sparse_results, alpha, candidate_k)

        if rerank and settings.rerank_enabled and len(results) > k:
            results = await self._rerank(query, results, top_k=k)

        elapsed = (time.monotonic() - start) * 1000

        return {
            "query": query,
            "results": [
                {
                    "chunk_id": r.get("id", ""),
                    "score": round(r.get("score", 0), 4),
                    "rerank_score": round(r.get("rerank_score", 0), 4),
                    "content_preview": (r.get("document") or "")[:200],
                    "metadata": r.get("metadata", {}),
                }
                for r in results[:k]
            ],
            "total_found": len(results),
            "latency_ms": int(elapsed),
        }

    async def search_for_eval(
        self,
        query: str,
        kb_id: str,
        k: int = 5,
        alpha: float = 0.6,
    ) -> dict:
        """Full-chain retrieval for quality evaluation — mirrors production retrieval.

        Runs Query Standardization → Dense+BM25 → RRF → (Cross-Encoder Rerank) →
        Top-K, i.e. the *same* retrieval path as ``generate_answer`` (including
        the query standardizer and sub-queries). ``search_only`` skips the
        standardizer, so it would under-measure the real pipeline — the quality
        gate must use this method instead.

        Returns the same ``results`` shape as ``search_only`` (each item has
        ``chunk_id`` + ``metadata`` with ``doc_id``/``doc_title``).
        """
        start = time.monotonic()

        # 0. Standardize query (production retrieval path — primary + sub-queries)
        standardizer = get_query_standardizer()
        std_result = await standardizer.process(
            query=query,
            history=None,
            intent=Intent.KNOWLEDGE,
        )
        primary = std_result.primary_query or query
        sub_queries = std_result.sub_queries

        # 1. Full retrieval chain (_retrieve already applies RRF + rerank internally)
        results = await self._retrieve(
            query=primary,
            kb_id=kb_id,
            k=k,
            alpha=alpha,
            sub_queries=sub_queries,
        )

        elapsed = (time.monotonic() - start) * 1000

        return {
            "query": query,
            "results": [
                {
                    "chunk_id": r.get("id", ""),
                    "score": round(r.get("score", 0), 4),
                    "rerank_score": round(r.get("rerank_score", 0), 4),
                    "content_preview": (r.get("document") or "")[:200],
                    "metadata": r.get("metadata", {}),
                }
                for r in results[:k]
            ],
            "total_found": len(results),
            "latency_ms": int(elapsed),
        }

    async def generate_answer(
        self,
        query: str,
        kb_id: str,
        conversation_history: list[dict] | None = None,
        k: int = 5,
        alpha: float = 0.6,
        intent: Intent = Intent.KNOWLEDGE,
    ) -> dict:
        """Generate a complete answer with source citations.

        Args:
            query: Original user input (preserved for prompt).
            kb_id: Knowledge base ID.
            conversation_history: Recent messages for context.
            k: Number of chunks to retrieve.
            alpha: Dense/sparse fusion weight.
            intent: Classified intent — determines standardization depth.
        """
        start = time.monotonic()

        # 0. Standardize query for retrieval (if knowledge/clarification)
        standardizer = get_query_standardizer()
        std_result = await standardizer.process(
            query=query,
            history=conversation_history,
            intent=intent,
        )

        # 1. Retrieve relevant chunks — use standardized query for embedding
        if intent in (Intent.KNOWLEDGE, Intent.CLARIFICATION):
            retrieved = await self._retrieve(
                query=std_result.primary_query,
                kb_id=kb_id,
                k=k,
                alpha=alpha,
                sub_queries=std_result.sub_queries,
            )
        else:
            retrieved = []

        # 2. Build prompt — use ORIGINAL query so LLM knows what user asked
        system_prompt, user_prompt = self._build_prompt(
            query, retrieved, conversation_history
        )

        # 3. Generate
        answer = await self.llm.generate(
            prompt=user_prompt,
            system_prompt=system_prompt,
        )

        # 4. Format with citations
        formatted_answer = self._format_answer(answer, retrieved)

        latency_ms = int((time.monotonic() - start) * 1000)
        prompt_tokens = await self.llm.count_tokens(system_prompt + user_prompt)
        completion_tokens = await self.llm.count_tokens(answer)

        sources = [
            {
                "chunk_id": r.get("id", ""),
                "doc_title": r.get("metadata", {}).get("doc_title", "Unknown"),
                "content_preview": (r.get("document") or "")[:150],
                "score": round(r.get("score", 0), 4),
                "rerank_score": round(r.get("rerank_score", 0), 4),
                "chunk_type": r.get("metadata", {}).get("chunk_type", "text"),
            }
            for r in retrieved[:k]
        ]

        return {
            "answer": formatted_answer,
            "sources": sources,
            "latency_ms": latency_ms,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "standardized_query": std_result.primary_query,
        }

    async def generate_stream(
        self,
        query: str,
        kb_id: str,
        conversation_history: list[dict] | None = None,
        k: int = 5,
        alpha: float = 0.6,
        intent: Intent = Intent.KNOWLEDGE,
    ) -> AsyncGenerator[dict, None]:
        """Stream an answer with SSE events.

        Args:
            query: Original user input (preserved for display).
            kb_id: Knowledge base ID.
            conversation_history: Recent messages for context.
            k: Number of chunks to retrieve.
            alpha: Dense/sparse fusion weight.
            intent: Classified intent — determines standardization depth.
        """
        start = time.monotonic()

        # ── Phase 1: Analyzing ──────────────────────────────────────
        yield {"type": "phase", "phase": "analyzing", "message": "正在分析问题..."}

        # 0. Standardize query for retrieval
        standardizer = get_query_standardizer()
        std_result = await standardizer.process(
            query=query,
            history=conversation_history,
            intent=intent,
        )

        # ── Phase 2: Searching ──────────────────────────────────────
        yield {"type": "phase", "phase": "searching", "message": "正在检索相关知识..."}

        # 1. Use standardized query for retrieval
        if intent in (Intent.KNOWLEDGE, Intent.CLARIFICATION):
            retrieved = await self._retrieve(
                query=std_result.primary_query,
                kb_id=kb_id,
                k=k,
                alpha=alpha,
                sub_queries=std_result.sub_queries,
            )
            # Log whether query took fast path (for diagnostics)
            if std_result.fast_path:
                logger.debug(
                    "Fast path: query='%s' → rewritten='%s' (saved ~3-10s LLM)",
                    query[:60], std_result.primary_query[:60],
                )
        else:
            retrieved = []

        sources = [
            {
                "chunk_id": r.get("id", ""),
                "doc_title": r.get("metadata", {}).get("doc_title", "Unknown"),
                "content_preview": (r.get("document") or "")[:150],
                "score": round(r.get("score", 0), 4),
                "rerank_score": round(r.get("rerank_score", 0), 4),
            }
            for r in retrieved[:k]
        ]
        yield {"type": "sources", "sources": sources}

        # ── Phase 3: Generating ─────────────────────────────────────
        yield {"type": "phase", "phase": "generating", "message": "正在生成回答..."}

        # 2. Build prompt — use ORIGINAL query
        system_prompt, user_prompt = self._build_prompt(
            query, retrieved, conversation_history
        )

        # 3. Stream tokens
        full_answer = ""
        async for token in self.llm.generate_stream(
            prompt=user_prompt, system_prompt=system_prompt
        ):
            full_answer += token
            yield {"type": "token", "content": token}

        # 4. Done
        latency_ms = int((time.monotonic() - start) * 1000)
        full_answer = self._format_answer(full_answer, retrieved)
        yield {
            "type": "done",
            "content": full_answer,
            "sources": sources,
            "latency_ms": latency_ms,
            "standardized_query": std_result.primary_query,
        }

    async def _retrieve(
        self,
        query: str,
        kb_id: str,
        k: int,
        alpha: float,
        sub_queries: list[str] | None = None,
    ) -> list[dict]:
        """Internal retrieval step with expanded recall + optional re-ranking.

        Stage pipeline:
            1. Dense retrieval  (candidate_k)
            2. BM25 retrieval   (candidate_k)
            3. RRF fusion       (candidate_k)
            4. Sub-query merge  (if applicable)
            5. Cross-encoder    (if enabled) → top-k

        When sub_queries are provided, each query is embedded and searched
        independently, then results are merge-deduplicated by chunk ID.
        """
        collection = f"kb_{kb_id}"

        # ── Expanded recall ─────────────────────────────────────
        candidate_k = max(k * 3, settings.rerank_candidate_k)

        query_embedding = await self.embedding_model.embed_text(query)
        dense_results = await self.vector_store.search(
            collection_name=collection,
            query_embedding=query_embedding,
            k=candidate_k,
        )
        sparse_results = await self._sparse_search(query, collection, candidate_k)
        all_results = self._hybrid_fusion(dense_results, sparse_results, alpha, candidate_k)

        # ── Sub-query retrieval (multi-query fusion) ─────────────
        if sub_queries:
            for sub_q in sub_queries[:3]:
                try:
                    sub_embedding = await self.embedding_model.embed_text(sub_q)
                    sub_dense = await self.vector_store.search(
                        collection_name=collection,
                        query_embedding=sub_embedding,
                        k=max(k * 2, settings.rerank_output_k),
                    )
                    all_results.extend(sub_dense)
                except Exception:
                    pass

            # Merge-deduplicate: keep highest score per chunk ID
            seen: dict[str, dict] = {}
            for item in all_results:
                cid = item.get("id", "")
                if cid not in seen or item.get("score", 0) > seen[cid].get("score", 0):
                    seen[cid] = item

            # Re-rank by score
            all_results = sorted(
                seen.values(), key=lambda x: x.get("score", 0), reverse=True
            )

        # ── Cross-encoder re-ranking (only when we have > k candidates) ──
        if settings.rerank_enabled and all_results and len(all_results) > k:
            all_results = await self._rerank(query, all_results, top_k=k)
        else:
            all_results = all_results[:k]

        return all_results

    async def _sparse_search(self, query: str, collection: str, k: int) -> list[dict]:
        """BM25 sparse retrieval over ChromaDB documents.

        Uses BM25SparseRetriever with automatic index build/refresh.
        Returns results in the same format as dense search.
        """
        from app.core.rag.retrieval.bm25_retriever import BM25SparseRetriever
        try:
            return await BM25SparseRetriever.search(
                query=query,
                collection_name=collection,
                k=k,
                vector_store=self.vector_store,
            )
        except Exception:
            # Fallback: if BM25 fails (e.g. empty collection), return empty
            return []

    def _hybrid_fusion(
        self, dense: list[dict], sparse: list[dict], alpha: float, k: int
    ) -> list[dict]:
        """Weighted reciprocal rank fusion."""
        if not sparse:
            return dense[:k]
        if not dense:
            return sparse[:k]

        scores: dict[str, float] = {}

        for rank, item in enumerate(dense):
            scores[item["id"]] = alpha * (1.0 / (rank + 1))
        for rank, item in enumerate(sparse):
            rrf_score = (1 - alpha) * (1.0 / (rank + 1))
            scores[item["id"]] = scores.get(item["id"], 0) + rrf_score

        # Merge items by ID
        all_items = {r["id"]: r for r in dense}
        for r in sparse:
            if r["id"] not in all_items:
                all_items[r["id"]] = r

        ranked = sorted(
            all_items.values(),
            key=lambda x: scores.get(x["id"], 0),
            reverse=True,
        )
        return ranked[:k]

    async def _rerank(self, query: str, results: list[dict], top_k: int) -> list[dict]:
        """Cross-encoder re-ranking over RRF-fused candidates.

        Delegates to ``CrossEncoderReranker``. Falls back to top-k of the
        input list on any error so the RAG pipeline never breaks.
        """
        try:
            from app.core.rag.reranker import CrossEncoderReranker
            reranker = CrossEncoderReranker()
            return await reranker.rerank(
                query=query,
                documents=results,
                top_k=top_k,
            )
        except Exception as exc:
            logger.warning("Reranker failed (%s); returning RRF top-%d", exc, top_k)
            return results[:top_k]

    def _build_prompt(
        self,
        query: str,
        retrieved: list[dict],
        history: list[dict] | None = None,
    ) -> tuple[str, str]:
        """Build system and user prompts."""
        # Format retrieved chunks
        context_parts = []
        for i, chunk in enumerate(retrieved[:5], 1):
            doc_title = chunk.get("metadata", {}).get("doc_title", "Unknown")
            content = chunk.get("document", "")
            context_parts.append(f"[source:{i}] {doc_title}\n{content}")

        context = "\n\n---\n\n".join(context_parts)

        system_prompt = """You are a programming learning assistant. Answer the user's question based on the provided knowledge base excerpts. Follow these rules:
1. If the answer involves code, provide complete, runnable examples.
2. Explain concepts step by step, suitable for learners.
3. Always cite sources using [source:N] notation when referencing knowledge base content.
4. If you cannot answer from the provided knowledge base, say so clearly and suggest what the user might search for.
5. Format code blocks with proper language tags (```python, ```javascript, etc.).
6. Structure your answer: explanation first, then code examples if applicable, then a summary of key points.
7. At the end of your answer, add a standardized source citation footer using the exact format below depending on how much you used the provided context:

   - If your answer is PRIMARILY based on the knowledge base context provided above, use:
     ---
     📚 **参考来源**
     - [文档名] > [章节/标题]
       > 引用原文："...关键段落前80字..."
     ---

   - If your answer uses the knowledge base for core structure but adds significant reasoning, use:
     ---
     🔀 **内容说明**
     - 知识库支撑：[文档名] > [章节]，提供核心定义与代码示例
     - 模型补充：[补充内容描述] 由模型推理生成
     ---

Fill in the actual document names, titles and quotes from the context provided."""

        # Format history
        history_text = ""
        if history:
            for msg in history[-6:]:  # Last 6 messages
                role = "User" if msg.get("role") == "user" else "Assistant"
                history_text += f"{role}: {msg.get('content', '')}\n"

        user_prompt = f"""Knowledge Base Context:
---
{context}
---

{f"Conversation History:\n{history_text}\n" if history_text else ""}
User Question: {query}

Please provide a thorough answer with explanations and code examples where relevant. Remember to include the standardized source citation footer at the end of your answer."""

        return system_prompt, user_prompt

    def _format_answer(self, answer: str, retrieved: list[dict]) -> str:
        """Append standardized source citation footer if not already present."""
        # If answer already has a citation footer, leave it as-is
        if "📚" in answer or "🤖" in answer or "🔀" in answer:
            return answer

        # No retrieved chunks → pure model generation
        if not retrieved:
            return answer.rstrip() + "\n\n---\n🤖 **生成说明**\n此回答为模型基于训练数据生成，未引用特定外部知识库。建议通过官方文档或实际运行验证代码正确性。\n---"

        # Build knowledge-base citation
        sources_section = "\n\n---\n📚 **参考来源**\n"
        added = False
        for chunk in retrieved[:3]:
            doc_title = chunk.get("metadata", {}).get("doc_title", "Unknown")
            content = chunk.get("document", "")[:80].strip()
            score = chunk.get("score", 0)

            # Check topic/heading info from metadata
            topic = chunk.get("metadata", {}).get("topic", "")
            heading = f" > {topic}" if topic else ""

            sources_section += f"- {doc_title}{heading}\n"
            if content:
                sources_section += f"  > 引用原文：\"{content}\"\n"
            added = True

        if added:
            sources_section += "---"
            return answer.rstrip() + sources_section

        return answer
