"""Evaluation dataset management — annotation, run, results."""
from __future__ import annotations

import math
import time
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.feedback import EvalDataset, EvalQAPair, EvalResult
from app.models.user import User
from app.core.rag.pipeline import RAGPipeline
# NOTE: 指标函数均在 run_evaluation 内按需导入（metrics.py 重构后
# 顶层旧名字 recall_at_k/hit_rate_at_k/mrr 已不存在，曾导致
# eval 模块 ImportError 500——2026-08-16 修复）


class EvalDatasetService:
    @staticmethod
    async def list_datasets(
        db: AsyncSession, page: int, page_size: int
    ) -> tuple[list[EvalDataset], int]:
        result = await db.execute(
            select(EvalDataset).offset((page - 1) * page_size).limit(page_size)
        )
        items = result.scalars().all()
        total_result = await db.execute(select(func.count(EvalDataset.id)))
        total = total_result.scalar()
        return list(items), total

    @staticmethod
    async def create_dataset(
        db: AsyncSession, user: User, data
    ) -> EvalDataset:
        ds = EvalDataset(
            id=uuid.uuid4(),
            name=data.name,
            description=data.description,
            kb_id=data.kb_id,
            created_by=user.id,
        )
        db.add(ds)
        await db.flush()
        return ds

    @staticmethod
    async def add_qa_pairs(
        db: AsyncSession, ds_id, pairs: list
    ) -> list[EvalQAPair]:
        """Add QA pairs with support for both legacy and new ground truth fields."""
        items = []
        for p in pairs:
            pair = EvalQAPair(
                id=uuid.uuid4(),
                dataset_id=ds_id,
                question=p.question,
                reference_answer=p.reference_answer,
                # Document-level GT（UUID → str，JSON 列不可序列化 UUID）
                relevant_doc_ids=(
                    [str(did) for did in p.relevant_doc_ids]
                    if hasattr(p, "relevant_doc_ids") and p.relevant_doc_ids
                    else None
                ),
                relevant_doc_titles=(
                    p.relevant_doc_titles if hasattr(p, "relevant_doc_titles") else None
                ),
                # Chunk-level GT
                ground_truth_chunk_ids=(
                    p.ground_truth_chunk_ids
                    if hasattr(p, "ground_truth_chunk_ids")
                    else None
                ),
                ground_truth_chunk_id_type=(
                    p.ground_truth_chunk_id_type
                    if hasattr(p, "ground_truth_chunk_id_type")
                    else "vector_id"
                ),
                # Answer span (optional)
                answer_span=p.answer_span if hasattr(p, "answer_span") else None,
                ground_truth_notes=(
                    p.ground_truth_notes if hasattr(p, "ground_truth_notes") else None
                ),
                subject=p.subject if hasattr(p, "subject") else None,
                # Legacy fallback
                expected_chunk_ids=(
                    [str(cid) for cid in p.expected_chunk_ids]
                    if hasattr(p, "expected_chunk_ids") and p.expected_chunk_ids
                    else None
                ),
                difficulty=p.difficulty,
                tags=p.tags,
            )
            db.add(pair)
            items.append(pair)
        await db.flush()
        return items

    @staticmethod
    async def run_evaluation(
        db: AsyncSession, ds_id, config: dict
    ) -> dict:
        """Run full evaluation over all QA pairs in a dataset.

        Uses ``ground_truth_chunk_ids`` (preferred) or falls back to
        ``expected_chunk_ids`` for each QA pair.

        Returns summary metrics including the new Hit Rate and NDCG.
        """
        result = await db.execute(
            select(EvalQAPair).where(EvalQAPair.dataset_id == ds_id)
        )
        pairs = result.scalars().all()

        ds_result = await db.execute(
            select(EvalDataset).where(EvalDataset.id == ds_id)
        )
        dataset = ds_result.scalar_one_or_none()

        pipeline = RAGPipeline()
        results = []

        for pair in pairs:
            start = time.monotonic()
            answer = await pipeline.generate_answer(
                query=pair.question,
                kb_id=str(dataset.kb_id) if dataset and dataset.kb_id else "default",
                k=config.get("k", 5),
                alpha=config.get("alpha", 0.6),
            )
            latency_ms = int((time.monotonic() - start) * 1000)

            # ── Extract retrieved info ──────────────────────────────
            retrieved = answer.get("sources", [])
            retrieved_chunks = [s["chunk_id"] for s in retrieved]
            retrieved_docs = [
                s.get("metadata", {}).get("doc_id", "")
                if isinstance(s.get("metadata"), dict)
                else ""
                for s in retrieved
            ]
            top_k = config.get("k", 5)

            # ── Document-level ground truth ─────────────────────────
            doc_ids = pair.relevant_doc_ids or []
            doc_ids_str = [str(did) for did in doc_ids]

            # ── Chunk-level ground truth ────────────────────────────
            gt_ids = pair.ground_truth_chunk_ids or pair.expected_chunk_ids or []
            expected_chunk_ids = [str(cid) for cid in gt_ids]

            # ── Compute all metrics ─────────────────────────────────
            from app.core.evaluation.metrics import (
                doc_hit_at_k, doc_mrr, ndcg_at_k,
                chunk_recall_at_k, chunk_hit_at_k,
            )

            dhr5 = doc_hit_at_k(retrieved_docs, doc_ids_str, k=top_k) if doc_ids_str else None
            dmrr = doc_mrr(retrieved_docs, doc_ids_str) if doc_ids_str else None
            ndcg = ndcg_at_k(retrieved_docs, doc_ids_str, k=top_k) if doc_ids_str else None

            cr1 = chunk_recall_at_k(retrieved_chunks, expected_chunk_ids, k=1) if expected_chunk_ids else None
            cr3 = chunk_recall_at_k(retrieved_chunks, expected_chunk_ids, k=3) if expected_chunk_ids else None
            cr5 = chunk_recall_at_k(retrieved_chunks, expected_chunk_ids, k=top_k) if expected_chunk_ids else None
            chr5 = chunk_hit_at_k(retrieved_chunks, expected_chunk_ids, k=top_k) if expected_chunk_ids else None
            cmrr = doc_mrr(retrieved_chunks, expected_chunk_ids) if expected_chunk_ids else None  # chunk MRR uses same formula

            result_entry = EvalResult(
                id=uuid.uuid4(),
                qa_pair_id=pair.id,
                # Document-level
                doc_hit_at_5=dhr5,
                doc_mrr=dmrr,
                ndcg_at_5=ndcg,
                # Chunk-level
                recall_at_1=cr1,
                recall_at_3=cr3,
                recall_at_5=cr5,
                hit_rate_at_5=chr5,
                mrr=cmrr,
                generated_answer=answer.get("answer", ""),
                retrieved_chunk_ids=[rid for rid in retrieved_chunks if rid],
                latency_ms=latency_ms,
            )
            db.add(result_entry)
            results.append(result_entry)

        await db.flush()

        # ── Summary ────────────────────────────────────────────────
        n = max(1, len(results))
        avg_doc_hit = sum((r.doc_hit_at_5 or 0) for r in results) / n
        avg_doc_mrr = sum((r.doc_mrr or 0) for r in results) / n
        avg_ndcg = sum((r.ndcg_at_5 or 0) for r in results) / n
        avg_chunk_recall = sum((r.recall_at_5 or 0) for r in results) / n
        avg_chunk_hit = sum((r.hit_rate_at_5 or 0) for r in results) / n
        avg_latency = sum((r.latency_ms or 0) for r in results) / n

        return {
            "dataset_id": str(ds_id),
            "total_pairs": len(pairs),
            # Primary: document-level
            "avg_doc_hit_at_5": round(avg_doc_hit, 4),
            "avg_doc_mrr": round(avg_doc_mrr, 4),
            "avg_ndcg_at_5": round(avg_ndcg, 4),
            # Auxiliary: chunk-level
            "avg_chunk_recall_at_5": round(avg_chunk_recall, 4),
            "avg_chunk_hit_at_5": round(avg_chunk_hit, 4),
            "avg_latency_ms": int(avg_latency),
            "results": [
                {
                    "qa_pair_id": str(r.qa_pair_id),
                    "doc_hit_at_5": r.doc_hit_at_5,
                    "doc_mrr": r.doc_mrr,
                    "ndcg_at_5": r.ndcg_at_5,
                    "chunk_recall_at_5": r.recall_at_5,
                    "chunk_hit_at_5": r.hit_rate_at_5,
                    "latency_ms": r.latency_ms,
                }
                for r in results
            ],
        }

    @staticmethod
    async def run_ablation(
        db: AsyncSession, ds_id, configs: list[dict]
    ) -> list[dict]:
        """Run multiple evaluation configs and return comparable results.

        ``configs`` is a list of dicts, each like::

            {
                "name": "Exp1-bge-zh",
                "k": 5,
                "alpha": 0.5,
                "strategy": "hybrid",
                "rerank": False,
                "embedding_model": "BAAI/bge-small-zh-v1.5",
                "rerank_model": None,
            }

        Returns a list of result dicts (one per config) suitable for
        building a LaTeX comparison table.
        """
        from app.config import settings as app_settings

        original_embedding = app_settings.embedding_model
        original_rerank = app_settings.rerank_model
        original_rerank_enabled = app_settings.rerank_enabled

        results = []
        for cfg in configs:
            # Override settings
            if cfg.get("embedding_model"):
                app_settings.embedding_model = cfg["embedding_model"]
            if cfg.get("rerank_model"):
                app_settings.rerank_model = cfg["rerank_model"]
                app_settings.rerank_enabled = True
            else:
                app_settings.rerank_enabled = cfg.get("rerank", False)

            eval_result = await EvalDatasetService.run_evaluation(db, ds_id, cfg)
            eval_result["config_name"] = cfg["name"]
            results.append(eval_result)

        # Restore
        app_settings.embedding_model = original_embedding
        app_settings.rerank_model = original_rerank
        app_settings.rerank_enabled = original_rerank_enabled

        return results

    @staticmethod
    async def get_results(db: AsyncSession, ds_id) -> list:
        result = await db.execute(
            select(EvalResult)
            .join(EvalQAPair)
            .where(EvalQAPair.dataset_id == ds_id)
        )
        return result.scalars().all()
