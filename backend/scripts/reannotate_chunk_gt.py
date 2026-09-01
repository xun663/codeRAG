#!/usr/bin/env python3
"""重标注 chunk 级 GT 到当前索引（修复 Chunk 标注偏移）。

背景: 向量集合重建后（标题增强索引，2026-08-06），chroma id 改为
DB DocumentChunk.id，但评估数据集中的 ground_truth_chunk_ids 仍是
重建前的旧 id → chunk 级指标（context_recall）恒为 0。

方法: 对每个 QA 对，以「标注说明 + 问题文本」为查询，在目标文档
（relevant_doc_ids[0]）的当前 chunks 上做 embedding 语义匹配，
取 top-2 作为新的 ground_truth_chunk_ids（= 当前 vector_id）。

安全: 修改前完整备份到 data/chunk_gt_backup.json；逐条打印
旧→新 id 与匹配内容预览供人工核对。
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.db.session import async_session_factory
from app.embedding.factory import get_embedding_model
from app.models.document import DocumentChunk
from app.models.feedback import EvalQAPair
from app.vector_store.factory import get_vector_store

# 目标数据集（fix_gt.py 修正过的可信数据集）
DATASETS = [
    "66be64a4-5929-4030-9be9-f160955ec948",  # Python
    "09c7c5ef-edc3-42bf-8845-650dbd91a34c",  # Java
]


def cosine(a: list[float], b: list[float]) -> float:
    import math
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb + 1e-9)


async def main() -> None:
    vs = get_vector_store()
    emb = get_embedding_model()
    # 当前索引里存在的 chunk id 全集（用于判定 stale）
    collections = {}
    for kb_id in ("126739c2-e665-4e69-ad59-14218fe5c95d", "34139461-a995-4f77-86bd-ced21883929d"):
        coll = f"kb_{kb_id}"
        docs = await vs.get_all_documents(coll)
        collections[coll] = {d.get("id") for d in docs}
        print(f"集合 {coll[:20]}...: {len(collections[coll])} chunks")

    backup = []
    async with async_session_factory() as db:
        pairs = (await db.execute(
            select(EvalQAPair).where(EvalQAPair.dataset_id.in_(DATASETS))
        )).scalars().all()

        updated = 0
        for p in pairs:
            gt = [str(x) for x in (p.ground_truth_chunk_ids or [])]
            if not gt:
                continue
            # 找属于哪个集合（按相关文档 → KB 无法直接知道，用前缀探测）
            target_coll = None
            for coll, ids in collections.items():
                if any(g[:36] in ids for g in gt):
                    target_coll = coll
                    break
            if target_coll:
                continue  # 全部 GT 仍在索引中，无需重标注

            # ── 目标文档：relevant_doc_ids[0] ──
            doc_ids = [str(d) for d in (p.relevant_doc_ids or [])]
            if not doc_ids:
                continue
            target_doc = doc_ids[0]

            chunks = (await db.execute(
                select(DocumentChunk).where(DocumentChunk.doc_id == target_doc)
            )).scalars().all()
            if not chunks:
                print(f"  [跳过] 文档无 chunk: {target_doc[:8]} ({p.question[:30]})")
                continue

            # ── 语义匹配：标注说明 + 问题 → 目标文档内 top-2 ──
            query_text = f"{p.ground_truth_notes or ''} {p.question}".strip()
            qv = await emb.embed_text(query_text)
            scored = []
            for c in chunks:
                cv = await emb.embed_text(c.content[:1500])
                scored.append((cosine(qv, cv), c))
            scored.sort(key=lambda x: x[0], reverse=True)
            new_ids = [str(c.id) for _, c in scored[:2]]

            backup.append({
                "qa_pair_id": str(p.id),
                "question": p.question,
                "old_chunk_ids": gt,
                "new_chunk_ids": new_ids,
                "scores": [round(s, 4) for s, _ in scored[:2]],
                "matched_previews": [c.content[:60].replace("\n", " ") for _, c in scored[:2]],
            })
            p.ground_truth_chunk_ids = new_ids
            p.ground_truth_chunk_id_type = "vector_id"
            p.ground_truth_notes = (p.ground_truth_notes or "") + " [chunk GT 重标注 2026-08-15]"
            updated += 1
            print(f"  [{updated}] {p.question[:36]}")
            print(f"      旧: {[x[:8] for x in gt]} → 新: {[x[:8] for x in new_ids]}")
            for s, c in scored[:2]:
                print(f"      sim={s:.3f} | {c.content[:50].replace(chr(10), ' ')}")

        if not backup:
            print("没有需要重标注的 QA 对")
            return
        out = Path(__file__).resolve().parent.parent / "data" / "chunk_gt_backup.json"
        out.write_text(json.dumps(backup, ensure_ascii=False, indent=2), encoding="utf-8")
        await db.commit()
        print(f"\n完成: 重标注 {updated} 对 QA → {out}")


if __name__ == "__main__":
    asyncio.run(main())
