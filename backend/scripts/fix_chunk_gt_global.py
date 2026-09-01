#!/usr/bin/env python3
"""全库范围重标注 chunk GT（修复"文档内标注"导致的归属偏差）。

背景: 2026-08-15 的重标注限定在 relevant_doc_ids[0] 的文档内匹配 chunk，
但 Python 官方教程的历史文档归属本身有偏差（如"生成器"被标到 glossary.md
术语表），导致 GT 标到错误 chunk、context_recall 被系统性低估
（Python 0.6786 < Java 0.7692 是标注假象，非真实检索差异）。

本次: 在全库所有 chunks 里按「问题+标注说明」语义匹配 top-1，
GT chunk 即"真实答案位置"，同时修正 relevant_doc_ids 为该 chunk 所属文档。

用法: python fix_chunk_gt_global.py
"""
from __future__ import annotations

import asyncio
import json
import math
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.db.session import async_session_factory
from app.embedding.factory import get_embedding_model
from app.models.document import DocumentChunk
from app.models.feedback import EvalQAPair

DATASETS = [
    "66be64a4-5929-4030-9be9-f160955ec948",  # Python
    "09c7c5ef-edc3-42bf-8845-650dbd91a34c",  # Java
]
KB_IDS = {
    "66be64a4-5929-4030-9be9-f160955ec948": "126739c2-e665-4e69-ad59-14218fe5c95d",
    "09c7c5ef-edc3-42bf-8845-650dbd91a34c": "34139461-a995-4f77-86bd-ced21883929d",
}


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb + 1e-9)


async def main() -> None:
    emb = get_embedding_model()
    backup = []

    async with async_session_factory() as db:
        for ds_id in DATASETS:
            kb_id = KB_IDS[ds_id]
            # 该 KB 全部 chunks（embedding 缓存）
            chunks = (await db.execute(
                select(DocumentChunk).where(DocumentChunk.kb_id == kb_id)
            )).scalars().all()
            print(f"库 chunks: {len(chunks)}")
            chunk_vecs = {}
            for c in chunks:
                chunk_vecs[c.id] = await emb.embed_text(c.content[:1500])
            print("  chunk embeddings 完成")

            pairs = (await db.execute(
                select(EvalQAPair).where(EvalQAPair.dataset_id == ds_id)
            )).scalars().all()

            for p in pairs:
                query_text = f"{p.ground_truth_notes or ''} {p.question}".strip()
                qv = await emb.embed_text(query_text)
                best, best_score = None, -1
                for c in chunks:
                    s = cosine(qv, chunk_vecs[c.id])
                    if s > best_score:
                        best, best_score = c, s

                old_chunks = [str(x) for x in (p.ground_truth_chunk_ids or [])]
                old_docs = [str(x) for x in (p.relevant_doc_ids or [])]
                backup.append({
                    "qa_pair_id": str(p.id),
                    "question": p.question,
                    "old_chunk_ids": old_chunks,
                    "old_doc_ids": old_docs,
                    "new_chunk_id": str(best.id),
                    "new_doc_id": str(best.doc_id),
                    "sim": round(best_score, 4),
                    "preview": best.content[:60].replace("\n", " "),
                })
                p.ground_truth_chunk_ids = [str(best.id)]
                p.ground_truth_chunk_id_type = "vector_id"
                # 修正文档归属 = GT chunk 所属文档
                p.relevant_doc_ids = [str(best.doc_id)]
                p.ground_truth_notes = (p.ground_truth_notes or "") + " [全库重标注 2026-08-16]"
                print(f"  {p.question[:34]:<36} sim={best_score:.3f} | {best.content[:40].replace(chr(10),' ')}")

        out = Path(__file__).resolve().parent.parent / "data" / "chunk_gt_global_backup.json"
        out.write_text(json.dumps(backup, ensure_ascii=False, indent=2), encoding="utf-8")
        await db.commit()
        print(f"\n完成: {len(backup)} 对 QA 已全库重标注 → {out}")


if __name__ == "__main__":
    asyncio.run(main())
