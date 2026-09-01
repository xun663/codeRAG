#!/usr/bin/env python3
"""真实上下文召回率实测 — 修复 ID 空间错位后的诚实测量。

背景（已确认的三个问题）：
  1) GT chunk IDs 存的是 DocumentChunk.id（DB UUID）。
  2) Chroma 写入时用的是随机 uuid4，与 DB UUID 完全不同的 ID 空间，
     所以 GT chunk ID 与检索返回的 chunk_id 永远对不上 → Recall@5 恒 0。
  3) 重索引后 chunk 重建，DB UUID 也过期。

本脚本：
  Phase A — 诊断：逐 QA 验证
     · GT chunk ID 是否存在于 document_chunks 表
     · GT chunk ID 是否存在于 Chroma 集合（ID 空间一致性）
     · relevant_doc_ids 是否存在于 Chroma metadata.doc_id
  Phase B — 实测：用 doc 级 GT 解析到当前 Chroma ID 空间，计算
     · doc_hit@5（既有，对照）
     · context_hit@5（top5 中是否有来自相关文档的 chunk）
     · context_recall@5（top5 中相关 chunk 数 / min(5, 相关chunk总数)）

用法：
    cd backend && PYTHONUTF8=1 python scripts/true_context_recall.py
输出：
    true_context_recall_results.json
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
from app.models.feedback import EvalDataset, EvalQAPair
from app.models.document import Document, DocumentChunk
from app.core.rag.pipeline import RAGPipeline
from app.vector_store.factory import get_vector_store
from app.core.evaluation.metrics import doc_hit_at_k, doc_mrr, ndcg_at_k

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

CONFIGS = [
    {"name": "Dense-only", "strategy": "dense", "rerank": False},
    {"name": "Hybrid", "strategy": "hybrid", "rerank": False},
    {"name": "Hybrid+Reranker", "strategy": "hybrid", "rerank": True},
]
K = 5


async def load_chroma_index(store, kb_id: str) -> tuple[set, dict, int]:
    """Fetch all chroma entries for a KB collection.

    Returns (all_chroma_ids, chroma_by_doc_id, total_count).
    chroma_by_doc_id: doc_id -> set of chroma ids.
    """
    collection = f"kb_{kb_id}"
    docs = await store.get_all_documents(collection)
    all_ids = set()
    chroma_by_doc = {}
    for d in docs:
        all_ids.add(d["id"])
        meta = d.get("metadata") or {}
        doc_id = str(meta.get("doc_id") or "")
        if doc_id:
            chroma_by_doc.setdefault(doc_id, set()).add(d["id"])
    return all_ids, chroma_by_doc, len(docs)


async def diagnose_pairs(db, ds_label, ds_info, all_ids, chroma_by_doc, kb_doc_ids):
    """Phase A — ground-truth validity diagnostic."""
    qa_result = await db.execute(
        select(EvalQAPair)
        .where(EvalQAPair.dataset_id == ds_info["ds_id"])
        .order_by(EvalQAPair.created_at)
    )
    pairs = list(qa_result.scalars().all())

    stats = {
        "total": len(pairs),
        "with_gt_chunk_ids": 0,
        "gt_exists_in_db": 0,
        "gt_exists_in_chroma": 0,
        "gt_empty": 0,
        "with_doc_gt": 0,
        "doc_exists_in_chroma_meta": 0,
        "doc_exists_in_db": 0,
        "gt_in_both": 0,
        "gt_in_neither": 0,
    }

    for pair in pairs:
        gt_ids = [str(x) for x in (pair.ground_truth_chunk_ids or pair.expected_chunk_ids or [])]
        doc_ids = [str(x) for x in (pair.relevant_doc_ids or [])]

        if gt_ids:
            stats["with_gt_chunk_ids"] += 1
            # DB existence
            n_db = (
                await db.execute(
                    select(DocumentChunk.id).where(DocumentChunk.id.in_(gt_ids))
                )
            ).scalars().all()
            in_db = len(n_db) == len(gt_ids)
            # Chroma existence
            in_chroma = set(gt_ids) <= all_ids
            if in_db and in_chroma:
                stats["gt_in_both"] += 1
            elif not in_db and not in_chroma:
                stats["gt_in_neither"] += 1
            if in_db:
                stats["gt_exists_in_db"] += 1
            if in_chroma:
                stats["gt_exists_in_chroma"] += 1
        else:
            stats["gt_empty"] += 1

        if doc_ids:
            stats["with_doc_gt"] += 1
            if set(doc_ids) & set(kb_doc_ids):
                stats["doc_exists_in_db"] += 1
            if any(doc_id in chroma_by_doc for doc_id in doc_ids):
                stats["doc_exists_in_chroma_meta"] += 1

    return pairs, stats


async def resolve_relevant_chroma_ids(
    pair, kb_doc_ids, chroma_by_doc, db
) -> tuple[list, list]:
    """Resolve a QA pair's doc-level GT into the current Chroma ID space.

    Returns (relevant_chroma_ids, resolved_doc_ids).
    Falls back to title-substring match if relevant_doc_ids are stale.
    """
    doc_ids = [str(x) for x in (pair.relevant_doc_ids or [])]
    resolved = [d for d in doc_ids if d in chroma_by_doc]

    if not resolved:
        # Try title-substring fallback
        for title in (pair.relevant_doc_titles or []):
            if not title:
                continue
            rows = (
                await db.execute(
                    select(Document.id, Document.title).where(
                        Document.title.like(f"%{title}%")
                    )
                )
            ).all()
            for doc_id, _ in rows:
                did = str(doc_id)
                if did in chroma_by_doc and did not in resolved:
                    resolved.append(did)

    relevant_chroma = set()
    for did in resolved:
        relevant_chroma |= chroma_by_doc.get(did, set())
    return list(relevant_chroma), resolved


async def main():
    print("=" * 72)
    print("  真实上下文召回率实测（修复 ID 空间错位）")
    print("=" * 72)

    store = get_vector_store()
    pipeline = RAGPipeline()

    # Preload KB doc ids (DB) and chroma index per dataset
    async with async_session_factory() as db:
        db_docs = (
            await db.execute(select(Document.id, Document.kb_id))
        ).all()
        kb_doc_ids = {}
        for did, kb in db_docs:
            kb_doc_ids.setdefault(str(kb), []).append(str(did))

        out = {"timestamp": time.strftime("%Y-%m-%d %H:%M:%S"), "datasets": {}}

        for ds_label, ds_info in DATASETS.items():
            print(f"\n{'─' * 72}")
            print(f"  Dataset: {ds_label}  (kb={ds_info['kb_id']})")
            print(f"{'─' * 72}")

            kb_id = ds_info["kb_id"]
            all_ids, chroma_by_doc, chroma_total = await load_chroma_index(store, kb_id)
            print(f"  Chroma 集合条目: {chroma_total} | 涉及文档数: {len(chroma_by_doc)}")
            print(f"  DB documents in kb: {len(kb_doc_ids.get(kb_id, []))}")

            # ── Phase A: diagnostic ──────────────────────────────
            pairs, stats = await diagnose_pairs(
                db, ds_label, ds_info, all_ids, chroma_by_doc, set(kb_doc_ids.get(kb_id, []))
            )
            print("\n  [Phase A] GT 有效性诊断:")
            print(f"    QA 总数            : {stats['total']}")
            print(f"    有 chunk GT        : {stats['with_gt_chunk_ids']}   (空: {stats['gt_empty']})")
            print(f"    GT 存在于 DB 表    : {stats['gt_exists_in_db']}")
            print(f"    GT 存在于 Chroma   : {stats['gt_exists_in_chroma']}")
            print(f"    GT 两者都在        : {stats['gt_in_both']}")
            print(f"    GT 两者都不在      : {stats['gt_in_neither']}")
            print(f"    有 doc GT          : {stats['with_doc_gt']}")
            print(f"    doc GT 存在于 DB   : {stats['doc_exists_in_db']}")
            print(f"    doc GT 在 Chroma   : {stats['doc_exists_in_chroma_meta']}")

            # ── Phase B: true context recall ────────────────────
            print("\n  [Phase B] 真实上下文召回（doc级GT → Chroma ID空间）:")
            dataset_results = {}
            for cfg in CONFIGS:
                dhits, mrr_s, ndcgs = [], [], []
                c_hits, c_recs = [], []
                unresolved = 0
                t0 = time.monotonic()

                for pair in pairs:
                    try:
                        res = await pipeline.search_only(
                            query=pair.question,
                            kb_id=kb_id,
                            k=K,
                            strategy=cfg["strategy"],
                            rerank=cfg["rerank"],
                        )
                        retrieved = res.get("results", [])
                    except Exception as e:
                        print(f"    ❌ {pair.question[:40]}: {e}")
                        continue

                    ret_chunk_ids = [s["chunk_id"] for s in retrieved]
                    ret_docs = [
                        (s.get("metadata") or {}).get("doc_id", "") for s in retrieved
                    ]

                    # Doc-level (metadata.doc_id vs doc GT)
                    doc_ids = [str(x) for x in (pair.relevant_doc_ids or [])]
                    if doc_ids:
                        dhits.append(doc_hit_at_k(ret_docs, doc_ids, K))
                        mrr_s.append(doc_mrr(ret_docs, doc_ids))
                        ndcgs.append(ndcg_at_k(ret_docs, doc_ids, K))

                    # Corrected chunk GT in Chroma ID space
                    rel_chroma, resolved = await resolve_relevant_chroma_ids(
                        pair, set(kb_doc_ids.get(kb_id, [])), chroma_by_doc, db
                    )
                    if not rel_chroma:
                        unresolved += 1
                        continue
                    rel_set = set(rel_chroma)
                    matched = set(ret_chunk_ids) & rel_set
                    c_hits.append(1.0 if matched else 0.0)
                    c_recs.append(len(matched) / min(len(rel_set), K))

                n = max(1, len(c_hits))
                print(
                    f"    [{cfg['name']:<16}] "
                    f"doc_hit@5={sum(dhits)/max(1,len(dhits)):.1%}  "
                    f"context_hit@5={sum(c_hits)/n:.1%}  "
                    f"context_recall@5={sum(c_recs)/n:.1%}  "
                    f"(unresolved={unresolved})  {time.monotonic()-t0:.0f}s"
                )
                dataset_results[cfg["name"]] = {
                    "doc_hit_at_5": round(sum(dhits) / max(1, len(dhits)), 4),
                    "doc_mrr": round(sum(mrr_s) / max(1, len(mrr_s)), 4),
                    "ndcg_at_5": round(sum(ndcgs) / max(1, len(ndcgs)), 4),
                    "context_hit_at_5": round(sum(c_hits) / n, 4),
                    "context_recall_at_5": round(sum(c_recs) / n, 4),
                    "n_questions": len(pairs),
                    "n_unresolved_gt": unresolved,
                }

            out["datasets"][ds_label] = {"diagnostic": stats, "results": dataset_results}

    out_path = Path(__file__).resolve().parent.parent / "true_context_recall_results.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"\n💾 结果保存: {out_path}")
    print("\n✅ 完成。")


if __name__ == "__main__":
    asyncio.run(main())
