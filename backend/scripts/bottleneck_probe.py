#!/usr/bin/env python3
"""瓶颈定位探针 — 候选集召回 vs 重排后召回。

回答：上下文召回率低，瓶颈在候选生成还是重排？
  测量（生产配置 hybrid，candidate_k=30）：
    A) 候选集 top-30 的 doc_hit@30 —— 候选生成的质量上限
    B) 候选集 top-30 里正确 doc 的平均名次（MRR）
    C) 重排后 top-5 的 doc_hit@5 / context_recall@5 —— 最终输出
  如果 A 很高、C 低 → 瓶颈在重排；如果 A 也低 → 瓶颈在候选生成（embedding/BM25/分块）。

用法：
    cd backend && PYTHONUTF8=1 python scripts/bottleneck_probe.py
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.db.session import async_session_factory
from app.models.feedback import EvalQAPair
from app.core.rag.pipeline import RAGPipeline
from app.vector_store.factory import get_vector_store
from app.core.evaluation.metrics import doc_hit_at_k, doc_mrr

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

CANDIDATE_K = 30  # 生产 candidate_k（settings.rerank_candidate_k）


async def main():
    store = get_vector_store()
    pipeline = RAGPipeline()
    out = {}

    async with async_session_factory() as db:
        for label, ds_info in DATASETS.items():
            kb_id = ds_info["kb_id"]
            collection = f"kb_{kb_id}"
            entries = await store.get_all_documents(collection)
            chroma_by_doc = {}
            for e in entries:
                meta = e.get("metadata") or {}
                did = str(meta.get("doc_id") or "")
                if did:
                    chroma_by_doc.setdefault(did, set()).add(e["id"])

            pairs = (
                (await db.execute(
                    select(EvalQAPair).where(EvalQAPair.dataset_id == ds_info["ds_id"])
                ))
                .scalars()
                .all()
            )

            cand_hits, cand_mrrs, cand_doc_hit5 = [], [], []
            rerank_hits, rerank_recs, rerank_mrrs = [], [], []
            t0 = time.monotonic()

            for pair in pairs:
                doc_ids = [str(x) for x in (pair.relevant_doc_ids or [])]
                if not doc_ids:
                    continue

                # A) 候选集：hybrid, k=30, 不重排
                cand = await pipeline.search_only(
                    query=pair.question, kb_id=kb_id, k=CANDIDATE_K,
                    strategy="hybrid", rerank=False,
                )
                cand_docs = [
                    (s.get("metadata") or {}).get("doc_id", "") for s in cand.get("results", [])
                ]
                cand_hits.append(doc_hit_at_k(cand_docs, doc_ids, CANDIDATE_K))
                cand_mrrs.append(doc_mrr(cand_docs, doc_ids))
                cand_doc_hit5.append(doc_hit_at_k(cand_docs, doc_ids, 5))

                # C) 重排后：hybrid, rerank, 输出 top-5
                final = await pipeline.search_only(
                    query=pair.question, kb_id=kb_id, k=5,
                    strategy="hybrid", rerank=True,
                )
                final_docs = [
                    (s.get("metadata") or {}).get("doc_id", "") for s in final.get("results", [])
                ]
                final_chunks = [s["chunk_id"] for s in final.get("results", [])]
                rerank_hits.append(doc_hit_at_k(final_docs, doc_ids, 5))
                rerank_mrrs.append(doc_mrr(final_docs, doc_ids))

                # context_recall@5（doc级GT → chroma空间）
                rel = set()
                for did in doc_ids:
                    rel |= chroma_by_doc.get(did, set())
                if rel:
                    matched = set(final_chunks) & rel
                    rerank_recs.append(len(matched) / min(5, len(rel)))

            n = len(cand_hits)
            print(f"\n{'=' * 66}")
            print(f"  {label} ({n} QA) — 生产 hybrid, candidate_k={CANDIDATE_K}")
            print(f"{'=' * 66}")
            print(f"  A) 候选集 top-{CANDIDATE_K} doc_hit : {sum(cand_hits)/n:.1%}   (MRR {sum(cand_mrrs)/n:.3f})")
            print(f"  B) 候选集 top-5   doc_hit : {sum(cand_doc_hit5)/n:.1%}   ← 无重排的基线")
            print(f"  C) 重排后 top-5   doc_hit : {sum(rerank_hits)/n:.1%}   (MRR {sum(rerank_mrrs)/n:.3f})")
            print(f"  D) 重排后 context_recall@5: {sum(rerank_recs)/n:.1%}")
            print(f"  重排增益 (C−B): {sum(rerank_hits)/n - sum(cand_doc_hit5)/n:+.1%}")

            out[label] = {
                "candidate_doc_hit_at_30": round(sum(cand_hits) / n, 4),
                "candidate_mrr": round(sum(cand_mrrs) / n, 4),
                "candidate_doc_hit_at_5": round(sum(cand_doc_hit5) / n, 4),
                "reranked_doc_hit_at_5": round(sum(rerank_hits) / n, 4),
                "reranked_doc_mrr": round(sum(rerank_mrrs) / n, 4),
                "reranked_context_recall_at_5": round(sum(rerank_recs) / n, 4),
                "n": n,
            }

    out_path = Path(__file__).resolve().parent.parent / "bottleneck_probe_results.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"\n💾 {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
