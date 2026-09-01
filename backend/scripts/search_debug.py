#!/usr/bin/env python3
"""检索调试与审计工具 — 逐 QA pair 检查 Top5 是否包含正确内容。

用法：
    cd backend && HF_HUB_OFFLINE=0 PYTHONUTF8=1 python scripts/search_debug.py

输出：
    - 每个 QA pair 的详细检索结果
    - 人工审计所需的完整信息
    - 统计摘要

审计方法：
    对每个 QA pair，脚本展示检索结果和 ground truth 信息，
    人工判断三个问题：
    1. Top5 是否包含正确文档？
    2. chunk 标注是否偏移？
    3. 检索完全失败还是标注问题？
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.db.session import async_session_factory
from app.models.feedback import EvalDataset, EvalQAPair
from app.models.document import Document, DocumentChunk
from app.core.rag.pipeline import RAGPipeline
from app.vector_store.factory import get_vector_store


async def audit_one_qa(pipeline, pair, kb_id, db):
    """审计单个 QA pair 的检索结果与标注准确性。"""
    result = await pipeline.search_only(
        query=pair.question,
        kb_id=kb_id,
        k=5,
        strategy="hybrid",
        rerank=False,
    )

    # ── Ground truth 信息 ──
    gt_chunk_ids = set(pair.ground_truth_chunk_ids or [])

    # 找到标注的 chunk 在哪个文档
    gt_doc_titles = set()
    gt_chunk_contents = []
    for cid in gt_chunk_ids:
        chunk = (
            await db.execute(select(DocumentChunk).where(DocumentChunk.id == cid))
        ).scalar_one_or_none()
        if chunk:
            doc = (
                await db.execute(select(Document).where(Document.id == chunk.doc_id))
            ).scalar_one_or_none()
            gt_doc_titles.add(doc.title if doc else "?")
            gt_chunk_contents.append(
                f"  chunk[{chunk.chunk_index}]: {chunk.content[:80]}"
            )

    # ── 检索结果信息 ──
    top5_docs = set()
    top5_info = []
    for rank, r in enumerate(result["results"], 1):
        meta = r.get("metadata", {})
        doc_title = meta.get("doc_title", "?")
        top5_docs.add(doc_title)
        top5_info.append({
            "rank": rank,
            "chunk_id": r["chunk_id"],
            "doc_title": doc_title,
            "score": r["score"],
            "content_preview": r["content_preview"][:80],
        })

    # ── 审计判断 ──
    doc_hit = bool(gt_doc_titles & top5_docs)
    chunk_hit = bool(gt_chunk_ids & set(r["chunk_id"] for r in top5_info))
    correct_doc_rank = 0
    for r in top5_info:
        if r["doc_title"] in gt_doc_titles:
            correct_doc_rank = r["rank"]
            break

    return {
        "question": pair.question,
        "difficulty": pair.difficulty,
        "subject": pair.subject,
        "ground_truth": {
            "doc_titles": list(gt_doc_titles),
            "chunk_ids": list(gt_chunk_ids),
            "chunk_contents": gt_chunk_contents,
            "chunk_count": len(gt_chunk_ids),
        },
        "top5": top5_info,
        "audit": {
            "doc_hit": doc_hit,                    # 宽松：正确文档在 Top5
            "chunk_hit": chunk_hit,                 # 严格：正确 chunk ID 在 Top5
            "correct_doc_rank": correct_doc_rank,   # 正确文档的排名
            "verdict": (
                "✅ 正确文档命中" if doc_hit else
                "❌ 完全未命中"
            ) + (", chunk 索引偏移" if doc_hit and not chunk_hit else ""),
        },
    }


async def main():
    pipeline = RAGPipeline()
    store = get_vector_store()

    async with async_session_factory() as db:
        # 找最新 v2 数据集
        datasets = (
            (await db.execute(select(EvalDataset).where(EvalDataset.name.like("%v2%"))))
            .scalars()
            .all()
        )

        if not datasets:
            print("❌ 没有找到 v2 数据集")
            return

        all_audits = []

        for ds in datasets:
            print(f"\n{'=' * 70}")
            print(f"  数据集: {ds.name}")
            print(f"  ID: {ds.id}")
            print(f"  KB: {ds.kb_id}")
            print(f"{'=' * 70}")

            pairs = (
                (await db.execute(
                    select(EvalQAPair).where(EvalQAPair.dataset_id == ds.id)
                ))
                .scalars()
                .all()
            )

            print(f"\n  QA pairs: {len(pairs)}")
            print()

            for i, pair in enumerate(pairs, 1):
                audit = await audit_one_qa(
                    pipeline, pair, str(ds.kb_id), db
                )
                all_audits.append(audit)

                verdict = audit["audit"]["verdict"]
                print(f"  [{i:02d}] [{pair.difficulty:>5}] {pair.question[:50]}")
                print(f"        GT doc: {audit['ground_truth']['doc_titles']}")
                print(f"        Top5:   {[r['doc_title'] for r in audit['top5']]}")
                print(f"        {verdict}")
                print()

        # ── 统计摘要 ──
        print(f"\n{'=' * 70}")
        print(f"  审计统计")
        print(f"{'=' * 70}")

        total = len(all_audits)
        doc_hits = sum(1 for a in all_audits if a["audit"]["doc_hit"])
        chunk_hits = sum(1 for a in all_audits if a["audit"]["chunk_hit"])
        doc_only = doc_hits - chunk_hits  # 找到文档但 chunk 标注偏移

        print(f"\n  总 QA 数:         {total}")
        print(f"  ✅ 文档命中:       {doc_hits} ({doc_hits/total*100:.1f}%)")
        print(f"  ✅ 精确 chunk 命中: {chunk_hits} ({chunk_hits/total*100:.1f}%)")
        print(f"  ⚠️  文档命中但       {doc_only} ({doc_only/total*100:.1f}%)")
        print(f"     chunk 标注偏移:")
        print(f"  ❌ 完全未命中:      {total - doc_hits} ({(total-doc_hits)/total*100:.1f}%)")
        print()

        # 按数据集分类输出
        print("\n--- 各数据集详情 ---")
        for ds in datasets:
            ds_name = ds.name
            ds_audits = [a for a in all_audits if any(
                ds_name in str(a.get("question", ""))
                or str(a.get("subject", "")) in ds_name
            )]
        print()

        # 保存结果
        output = {
            "summary": {
                "total": total,
                "doc_hit_rate": round(doc_hits / total, 4) if total else 0,
                "chunk_hit_rate": round(chunk_hits / total, 4) if total else 0,
                "chunk_mismatch_rate": round(doc_only / total, 4) if total else 0,
                "miss_rate": round((total - doc_hits) / total, 4) if total else 0,
            },
            "audits": all_audits,
        }

        output_path = Path("search_debug_results.json")
        output_path.write_text(
            json.dumps(output, ensure_ascii=False, indent=2)
        )
        print(f"  💾 详细结果保存到: {output_path}")
        print(f"\n  查看单个 QA 详情: cat {output_path} | python -m json.tool")
        print(f"\n  ✅ 审计完成。请根据上述统计判断优化方向。")


if __name__ == "__main__":
    asyncio.run(main())
