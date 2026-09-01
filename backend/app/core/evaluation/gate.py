"""Quality Gate — automated retrieval-quality check for knowledge bases.

在设计上回答"上传者非专业，检索质量如何保证"：
质量不能靠上传者把关，而是由系统在发布前自动跑一次**检索级**评估
（不调用 LLM，只验证检索管道能否从 GT 问答对中找到正确文档/chunk），
双指标达标才把平台知识库标记为 verified。

Verdict rules（两个指标同时达标才 verified）:
  - avg_doc_hit_at_5           >= settings.gate_doc_hit_threshold       (默认 0.9)
  - avg_chunk_recall_at_5      >= settings.gate_context_recall_threshold (默认 0.6)
  - 若无 chunk 级 GT 的 QA 对，chunk 指标置空并跳过（不阻塞判定）

状态机: not_checked → verified / unverified / no_qa_data
"""
from __future__ import annotations

import time
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.evaluation.metrics import (
    chunk_recall_at_k,
    doc_hit_at_k,
    doc_mrr,
    ndcg_at_k,
)
from app.core.rag.pipeline import RAGPipeline
from app.models.feedback import EvalDataset, EvalQAPair
from app.models.knowledge_base import KnowledgeBase
from app.services.kb_service import KBService


class QualityGateService:
    """Run and persist the quality gate verdict for a knowledge base."""

    STATUS_NOT_CHECKED = "not_checked"
    STATUS_VERIFIED = "verified"
    STATUS_UNVERIFIED = "unverified"
    STATUS_NO_QA_DATA = "no_qa_data"

    @staticmethod
    async def _load_qa_pairs(db: AsyncSession, kb_id) -> list[EvalQAPair]:
        """Load all GT QA pairs from eval datasets bound to this KB.

        Deduplicates by question text — the same KB often has several
        dataset versions (e.g. "Python 问答集" 与 "Python 问答集 v2")
        with overlapping questions; counting them twice would skew the
        averaged metrics and waste retrieval calls.

        When duplicates exist, the pair from the NEWEST dataset wins:
        dataset versions represent re-annotated GT (e.g. chunk-level
        annotations fixed after a re-index), so stale annotations must
        not shadow the corrected ones.
        """
        result = await db.execute(
            select(EvalQAPair)
            .join(EvalDataset, EvalQAPair.dataset_id == EvalDataset.id)
            .where(EvalDataset.kb_id == kb_id)
            .order_by(EvalDataset.created_at.desc())
        )
        pairs: list[EvalQAPair] = []
        seen: set[str] = set()
        for p in result.scalars().all():
            key = (p.question or "").strip()
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            pairs.append(p)
        return pairs

    @staticmethod
    async def _persist(db: AsyncSession, kb: KnowledgeBase, status: str, report: dict) -> None:
        kb.quality_status = status
        kb.quality_metrics_json = report
        await db.flush()

    @staticmethod
    async def run_gate(
        db: AsyncSession,
        kb_id,
        pipeline: RAGPipeline | None = None,
    ) -> dict:
        """Run the retrieval-only quality gate against the KB's GT QA pairs.

        Args:
            kb_id: Target knowledge base.
            pipeline: Injectable for tests; defaults to the real RAG pipeline.

        Returns:
            Full gate report (also persisted onto the KB).
        """
        kb = await KBService._get_kb_or_404(db, kb_id)
        pairs = await QualityGateService._load_qa_pairs(db, kb_id)
        k = settings.gate_k
        run_at = datetime.now().isoformat()

        # ── No document-level GT → cannot verify ───────────────────
        doc_pairs = [p for p in pairs if p.relevant_doc_ids]
        if not doc_pairs:
            report = {
                "kb_id": str(kb_id),
                "status": QualityGateService.STATUS_NO_QA_DATA,
                "total_qa": len(pairs),
                "doc_level_pairs": 0,
                "chunk_level_pairs": 0,
                "metrics": {},
                "thresholds": {
                    "doc_hit_at_5": settings.gate_doc_hit_threshold,
                    "chunk_recall_at_5": settings.gate_context_recall_threshold,
                },
                "latency_ms": 0,
                "run_at": run_at,
                "per_pair": [],
                "reason": "No document-level ground-truth QA pairs for this KB — "
                          "cannot verify retrieval quality",
            }
            await QualityGateService._persist(db, kb, QualityGateService.STATUS_NO_QA_DATA, report)
            return report

        pipeline = pipeline or RAGPipeline()
        start = time.monotonic()

        doc_hit_sum = doc_mrr_sum = ndcg_sum = 0.0
        chunk_recall_sum = 0.0
        chunk_pairs = 0
        per_pair: list[dict] = []

        for pair in doc_pairs:
            search = await pipeline.search_only(
                query=pair.question,
                kb_id=str(kb_id),
                k=k,
                strategy="hybrid",
                rerank=True,
            )
            retrieved = search.get("results", [])
            retrieved_docs = [
                (r.get("metadata") or {}).get("doc_id", "") or ""
                for r in retrieved
            ]
            retrieved_chunks = [r.get("chunk_id", "") or "" for r in retrieved]

            # ── Document-level (primary) ───────────────────────────
            expected_docs = [str(did) for did in (pair.relevant_doc_ids or [])]
            dh5 = doc_hit_at_k(retrieved_docs, expected_docs, k=k)
            dmrr = doc_mrr(retrieved_docs, expected_docs)
            ndcg = ndcg_at_k(retrieved_docs, expected_docs, k=k)
            doc_hit_sum += dh5
            doc_mrr_sum += dmrr
            ndcg_sum += ndcg

            # ── Chunk-level (auxiliary) ────────────────────────────
            gt_chunks = [
                str(cid)
                for cid in (pair.ground_truth_chunk_ids or pair.expected_chunk_ids or [])
            ]
            cr5 = chunk_recall_at_k(retrieved_chunks, gt_chunks, k=k) if gt_chunks else None
            if gt_chunks:
                chunk_recall_sum += cr5
                chunk_pairs += 1

            per_pair.append({
                "qa_pair_id": str(pair.id),
                "question": pair.question[:80],
                "doc_hit_at_5": dh5,
                "doc_mrr": round(dmrr, 4),
                "ndcg_at_5": round(ndcg, 4),
                "chunk_recall_at_5": round(cr5, 4) if cr5 is not None else None,
            })

        n = max(1, len(doc_pairs))
        metrics = {
            "avg_doc_hit_at_5": round(doc_hit_sum / n, 4),
            "avg_doc_mrr": round(doc_mrr_sum / n, 4),
            "avg_ndcg_at_5": round(ndcg_sum / n, 4),
            "avg_chunk_recall_at_5": round(chunk_recall_sum / max(1, chunk_pairs), 4) if chunk_pairs else None,
            "chunk_level_pairs": chunk_pairs,
        }

        # ── Verdict ────────────────────────────────────────────────
        doc_pass = metrics["avg_doc_hit_at_5"] >= settings.gate_doc_hit_threshold
        chunk_pass = (
            metrics["avg_chunk_recall_at_5"] is None
            or metrics["avg_chunk_recall_at_5"] >= settings.gate_context_recall_threshold
        )
        status = (
            QualityGateService.STATUS_VERIFIED
            if doc_pass and chunk_pass
            else QualityGateService.STATUS_UNVERIFIED
        )

        report = {
            "kb_id": str(kb_id),
            "status": status,
            "total_qa": len(pairs),
            "doc_level_pairs": len(doc_pairs),
            "chunk_level_pairs": chunk_pairs,
            "metrics": metrics,
            "thresholds": {
                "doc_hit_at_5": settings.gate_doc_hit_threshold,
                "chunk_recall_at_5": settings.gate_context_recall_threshold,
            },
            "latency_ms": int((time.monotonic() - start) * 1000),
            "run_at": run_at,
            "per_pair": per_pair,
        }
        await QualityGateService._persist(db, kb, status, report)
        return report
