#!/usr/bin/env python3
"""实验 H：逐 query 排名审计 — 正确文档在各检索阶段掉队在哪一步。

对每个 QA 对，输出正确文档在四个阶段的各自名次：
    Dense  / BM25 / RRF fusion / Rerank
如果正确文档单路排名靠前、融合后掉队 → 融合问题；
如果单路就靠后 → 检索阶段问题（chunk 表示 / embedding）；
如果都在 top-30 但进不了 top-5 → 排序精选问题。

用法：
    cd backend && PYTHONUTF8=1 python scripts/rank_audit.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.db.session import async_session_factory
from app.models.feedback import EvalQAPair
from app.core.rag.pipeline import RAGPipeline
from app.vector_store.factory import get_vector_store

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

CANDIDATE_K = 30  # 与生产 candidate_k 对齐
ALPHA = 0.6


def doc_id_of(item: dict) -> str:
    return str((item.get("metadata") or {}).get("doc_id", ""))


def first_rank(results: list[dict], doc_ids: set[str]) -> int | None:
    """返回第一个命中正确 doc 的名次（0-based → 1-based）。未命中返回 None。"""
    for i, r in enumerate(results, start=1):
        if doc_id_of(r) in doc_ids:
            return i
    return None


async def main():
    store = get_vector_store()
    pipeline = RAGPipeline()
    out = {}

    async with async_session_factory() as db:
        for label, ds_info in DATASETS.items():
            kb_id = ds_info["kb_id"]
            collection = f"kb_{kb_id}"

            pairs = (
                (await db.execute(
                    select(EvalQAPair).where(EvalQAPair.dataset_id == ds_info["ds_id"])
                ))
                .scalars()
                .all()
            )

            rows = []
            dense_before_rrf = 0    # dense 进前5但 RRF 后掉出
            bm25_before_rrf = 0     # bm25 进前5但 RRF 后掉出
            rrf_has_correct = 0     # RRF top-30 含正确 doc
            rrf_top5 = 0            # RRF top-5 含正确 doc
            rerank_top5 = 0         # rerank top-5 含正确 doc

            for pair in pairs:
                doc_ids = {str(x) for x in (pair.relevant_doc_ids or [])}
                if not doc_ids:
                    continue
                q = pair.question

                # ── Dense ───────────────────────────────────────
                q_emb = await pipeline.embedding_model.embed_text(q)
                dense = await store.search(collection_name=collection, query_embedding=q_emb, k=CANDIDATE_K)
                d_rank = first_rank(dense, doc_ids)

                # ── BM25 ────────────────────────────────────────
                sparse = await pipeline._sparse_search(q, collection, CANDIDATE_K)
                s_rank = first_rank(sparse, doc_ids)

                # ── RRF fusion ──────────────────────────────────
                fused = pipeline._hybrid_fusion(dense, sparse, ALPHA, CANDIDATE_K)
                f_rank = first_rank(fused, doc_ids)
                f_top5 = [doc_id_of(r) for r in fused[:5]]

                # ── Rerank (top-30, 非 top-5，看全排序) ────────
                reranked = await pipeline._rerank(q, fused, top_k=CANDIDATE_K)
                r_rank = first_rank(reranked, doc_ids)
                r_top5 = [doc_id_of(r) for r in reranked[:5]]

                # ── 统计 ───────────────────────────────────────
                if d_rank is not None and d_rank <= 5 and (f_rank is None or f_rank > 5):
                    dense_before_rrf += 1
                if s_rank is not None and s_rank <= 5 and (f_rank is None or f_rank > 5):
                    bm25_before_rrf += 1
                if f_rank is not None:
                    rrf_has_correct += 1
                if f_rank is not None and f_rank <= 5:
                    rrf_top5 += 1
                if r_rank is not None and r_rank <= 5:
                    rerank_top5 += 1

                rows.append({
                    "q": q[:50],
                    "dense_rank": d_rank,
                    "bm25_rank": s_rank,
                    "rrf_rank": f_rank,
                    "rerank_rank": r_rank,
                })

            n = len(rows)
            print(f"\n{'=' * 78}")
            print(f"  {label} ({n} QA) — candidate_k={CANDIDATE_K}, alpha={ALPHA}")
            print(f"{'=' * 78}")
            print(f"  {'#':>2} {'query':<30} {'dense':>6} {'bm25':>6} {'rrf':>6} {'rerank':>6}")
            for i, r in enumerate(rows, start=1):
                q = r["q"] if len(r["q"]) <= 30 else r["q"][:29] + "…"
                print(f"  {i:>2} {q:<30} {str(r['dense_rank']):>6} {str(r['bm25_rank']):>6} "
                      f"{str(r['rrf_rank']):>6} {str(r['rerank_rank']):>6}")

            print(f"\n  ── 聚合 ──")
            print(f"  正确 doc 在 RRF top-30 中        : {rrf_has_correct}/{n} ({rrf_has_correct/n:.1%})")
            print(f"  正确 doc 在 RRF top-5           : {rrf_top5}/{n} ({rrf_top5/n:.1%})")
            print(f"  正确 doc 在 Rerank top-5        : {rerank_top5}/{n} ({rerank_top5/n:.1%})")
            print(f"  Dense 进前5但 RRF 掉出           : {dense_before_rrf}/{n}")
            print(f"  BM25 进前5但 RRF 掉出            : {bm25_before_rrf}/{n}")

            # 掉队归因
            dense_only = bm25_only = both = 0
            for r in rows:
                d, s = r["dense_rank"], r["bm25_rank"]
                if d is None and s is None:
                    continue
                if d is not None and s is not None:
                    both += 1
                elif d is not None:
                    dense_only += 1
                else:
                    bm25_only += 1
            print(f"  ── 召回来源 ──")
            print(f"  仅 dense 召回正确 doc  : {dense_only}/{n}")
            print(f"  仅 bm25 召回正确 doc  : {bm25_only}/{n}")
            print(f"  双路都召回             : {both}/{n}")

            out[label] = {
                "n": n,
                "rrf_has_correct_30": round(rrf_has_correct / n, 4),
                "rrf_top5": round(rrf_top5 / n, 4),
                "rerank_top5": round(rerank_top5 / n, 4),
                "dense_before_rrf": dense_before_rrf,
                "bm25_before_rrf": bm25_before_rrf,
                "rows": rows,
            }

    out_path = Path(__file__).resolve().parent.parent / "rank_audit_results.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"\n💾 {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
