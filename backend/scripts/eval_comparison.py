#!/usr/bin/env python3
"""Embedding model comparison — retrieval-only metrics, no LLM calls.

Usage:
    cd backend && PYTHONUTF8=1 python scripts/eval_comparison.py

Output:
    eval_comparison_results.json   — raw metrics per config & dataset
"""
from __future__ import annotations

import asyncio
import json
import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings
from app.db.session import async_session_factory
from app.models.feedback import EvalQAPair
from app.core.rag.pipeline import RAGPipeline
from app.core.evaluation.metrics import (
    doc_hit_at_k,
    doc_mrr,
    ndcg_at_k,
    chunk_recall_at_k,
    chunk_hit_at_k,
)
from sqlalchemy import select

# Evaluation datasets (v2, with relevant_doc_ids annotated)
DATASETS = {
    "Python": {
        "ds_id": "66be64a4-5929-4030-9be9-f160955ec948",
        "kb_id": "126739c2-e665-4e69-ad59-14218fe5c95d",
    },
    "Java": {
        "ds_id": "09c7c5ef-edc3-42bf-8845-650dbd91a34c",
        "kb_id": "34139461-a995-4f77-86bd-ced21883929d",
    },
}

# Configurations to test (all retrieval-only via search_only)
CONFIGS = [
    {
        "name": "Dense-only",
        "strategy": "dense",
        "rerank": False,
    },
    {
        "name": "Hybrid",
        "strategy": "hybrid",
        "rerank": False,
    },
    {
        "name": "Hybrid+Reranker",
        "strategy": "hybrid",
        "rerank": True,
    },
]

K = 5
ALPHA = 0.6


async def evaluate_config(
    kb_id: str,
    qa_pairs: list,
    strategy: str,
    rerank: bool,
) -> dict:
    """Run one config over one dataset's QA pairs (retrieval only)."""
    pipeline = RAGPipeline()
    doc_hits, doc_mrrs, ndcgs = [], [], []
    chunk_recs, chunk_hits = [], []
    errors = 0

    for pair in qa_pairs:
        try:
            search_result = await pipeline.search_only(
                query=pair.question,
                kb_id=kb_id,
                k=K,
                strategy=strategy,
                alpha=ALPHA,
                rerank=rerank,
            )
            retrieved = search_result.get("results", [])
        except Exception as e:
            print(f"    ❌ {pair.question[:40]}: {e}")
            retrieved = []
            errors += 1

        retrieved_chunks = [s.get("chunk_id", "") for s in retrieved]
        retrieved_docs = [
            s.get("metadata", {}).get("doc_id", "")
            if isinstance(s.get("metadata"), dict)
            else s.get("doc_id", "")
            for s in retrieved
        ]

        # Doc-level metrics
        doc_ids = [str(did) for did in (pair.relevant_doc_ids or [])]
        if doc_ids:
            doc_hits.append(doc_hit_at_k(retrieved_docs, doc_ids, K))
            doc_mrrs.append(doc_mrr(retrieved_docs, doc_ids))
            ndcgs.append(ndcg_at_k(retrieved_docs, doc_ids, K))

        # Chunk-level metrics
        gt_ids = [str(cid) for cid in (pair.ground_truth_chunk_ids or [])]
        if gt_ids:
            chunk_recs.append(chunk_recall_at_k(retrieved_chunks, gt_ids, K))
            chunk_hits.append(chunk_hit_at_k(retrieved_chunks, gt_ids, K))

    n_doc = max(1, len(doc_hits))
    n_chunk = max(1, len(chunk_recs))

    return {
        "total_questions": len(qa_pairs),
        "errors": errors,
        "doc_hit_at_5": round(sum(doc_hits) / n_doc, 4) if doc_hits else 0,
        "doc_mrr": round(sum(doc_mrrs) / n_doc, 4) if doc_mrrs else 0,
        "ndcg_at_5": round(sum(ndcgs) / n_doc, 4) if ndcgs else 0,
        "chunk_recall_at_5": round(sum(chunk_recs) / n_chunk, 4) if chunk_recs else 0,
        "chunk_hit_at_5": round(sum(chunk_hits) / n_chunk, 4) if chunk_hits else 0,
    }


async def main():
    model_name = settings.embedding_model
    print(f"{'=' * 70}")
    print(f"  Embedding Model : {model_name}")
    print(f"  Reranker Model  : {settings.rerank_model}")
    print(f"  Reranker Enabled: {settings.rerank_enabled}")
    print(f"{'=' * 70}")

    all_results = {
        "model": model_name,
        "reranker_model": settings.rerank_model,
        "rerank_enabled": settings.rerank_enabled,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "datasets": {},
    }
    total_time = 0.0

    async with async_session_factory() as db:
        for ds_label, ds_info in DATASETS.items():
            print(f"\n{'─' * 70}")
            print(f"  Dataset: {ds_label}")
            print(f"{'─' * 70}")

            # Load QA pairs
            qa_result = await db.execute(
                select(EvalQAPair)
                .where(EvalQAPair.dataset_id == ds_info["ds_id"])
                .order_by(EvalQAPair.created_at)
            )
            pairs = list(qa_result.scalars().all())
            print(f"  QA Pairs: {len(pairs)}")
            print()

            dataset_results = {}
            for cfg in CONFIGS:
                label = f"{cfg['strategy']}{'+Reranker' if cfg['rerank'] else ''}"
                print(f"  [{label}]", end=" ")
                sys.stdout.flush()

                start = time.monotonic()
                metrics = await evaluate_config(
                    ds_info["kb_id"], pairs, cfg["strategy"], cfg["rerank"]
                )
                elapsed = time.monotonic() - start
                total_time += elapsed

                print(f"  DocHit={metrics['doc_hit_at_5']:.1%}  "
                      f"MRR={metrics['doc_mrr']:.1%}  "
                      f"NDCG={metrics['ndcg_at_5']:.1%}  "
                      f"ChunkRec={metrics['chunk_recall_at_5']:.1%}  "
                      f"({elapsed:.0f}s)")

                dataset_results[cfg["name"]] = {
                    "metrics": {k: v for k, v in metrics.items()},
                    "time_seconds": round(elapsed, 1),
                }

            all_results["datasets"][ds_label] = dataset_results

    # ── Save ───────────────────────────────────────────────────────
    output_path = Path(__file__).resolve().parent.parent / "eval_comparison_results.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    print(f"\n{'=' * 70}")
    print(f"  Total time: {total_time:.0f}s")
    print(f"  Results: {output_path}")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    asyncio.run(main())
