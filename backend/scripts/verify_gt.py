#!/usr/bin/env python3
"""验证 GT 标注：输出实际使用数据集（66be64a4=Python, 09c7c5ef=Java）全部 QA 的
GT 文档标题 + 内容预览，用于人工判断标注是否正确。"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.db.session import async_session_factory
from app.models.document import Document, DocumentChunk
from app.models.feedback import EvalQAPair

DATASETS = {
    "Python": "66be64a4-5929-4030-9be9-f160955ec948",
    "Java": "09c7c5ef-edc3-42bf-8845-650dbd91a34c",
}


async def main():
    async with async_session_factory() as db:
        for label, ds_id in DATASETS.items():
            pairs = (
                (await db.execute(
                    select(EvalQAPair).where(EvalQAPair.dataset_id == ds_id)
                ))
                .scalars()
                .all()
            )
            print(f"\n{'=' * 80}\n  {label} 数据集 ({len(pairs)} QA)\n{'=' * 80}")
            for pair in pairs:
                doc_ids = [str(x) for x in (pair.relevant_doc_ids or [])]
                docs = (
                    (await db.execute(select(Document).where(Document.id.in_(doc_ids))))
                    .scalars()
                    .all()
                    if doc_ids
                    else []
                )
                print(f"\n■ Q: {pair.question}")
                print(f"  GT doc: {[d.title for d in docs]}")
                for d in docs:
                    chunk = (
                        (await db.execute(
                            select(DocumentChunk).where(DocumentChunk.doc_id == d.id).limit(1)
                        ))
                        .scalars()
                        .first()
                    )
                    content = (chunk.content or "")[:160].replace("\n", " ") if chunk else "(无 chunk)"
                    print(f"     '{d.title}' 预览: {content}")
                if pair.ground_truth_notes:
                    print(f"  标注备注: {pair.ground_truth_notes}")


if __name__ == "__main__":
    asyncio.run(main())
