"""Retrieval quality diagnostics."""
from __future__ import annotations


class KBDiagnostics:
    """Retrieval quality diagnostics and debugging."""

    @staticmethod
    async def check_retrieval_quality(
        query: str, kb_id: str, expected_chunks: list[str], k: int = 5
    ) -> dict:
        """Check how well the retrieval system finds expected chunks."""
        from app.core.rag.pipeline import RAGPipeline
        pipeline = RAGPipeline()
        result = await pipeline.search_only(query=query, kb_id=kb_id, k=k)

        retrieved_ids = [r["chunk_id"] for r in result["results"]]
        matched = set(retrieved_ids) & set(expected_chunks)
        recall = len(matched) / max(1, len(expected_chunks))

        # MRR for expected chunks
        mrr = 0.0
        for rank, rid in enumerate(retrieved_ids, 1):
            if rid in expected_chunks:
                mrr = 1.0 / rank
                break

        return {
            "query": query,
            "recall": round(recall, 4),
            "mrr": round(mrr, 4),
            "matched": list(matched),
            "missed": list(set(expected_chunks) - matched),
            "retrieved": [
                {"chunk_id": r["chunk_id"], "score": r["score"], "preview": r["content_preview"]}
                for r in result["results"]
            ],
        }

    @staticmethod
    async def get_missing_chunks(kb_id: str, top_n: int = 10) -> list[dict]:
        """Identify chunks that may need improvement (low quality or orphaned)."""
        # This would check for chunks with no retrieval hits in logs
        return []
