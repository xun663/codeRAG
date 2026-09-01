#!/usr/bin/env python3
"""清理重复文档：保留 GT 指向的 canonical 副本，删除其他重复。

删除前：
  1. 迁移 exercises.doc_id → canonical（避免孤儿题目）
  2. 删除 ChromaDB 中孤儿 doc_id 的向量
  3. 删除 DB document_chunks + documents

Python KB controlflow.md: 保留 10a42fb9，删 d6046639/da51d7a9/271a27f0/25097f49
Python KB 智能交互案例1.txt: 保留 810bf47e，删 fd6107e5
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text, update

from app.db.session import async_session_factory
from app.vector_store.factory import get_vector_store

PY_KB = "126739c2-e665-4e69-ad59-14218fe5c95d"
CANONICAL = "10a42fb9-80e8-482c-9d0b-814025627c01"  # controlflow.md 保留
DELETIONS = {
    # doc_id -> canonical (若为空则直接删无迁移)
    "d6046639-2c05-4069-81a1-ff445ab4cef5": CANONICAL,
    "da51d7a9-a219-4d71-9de7-c979f03224be": CANONICAL,
    "271a27f0-30f4-4b64-935b-848e85519a37": CANONICAL,
    "25097f49-b187-474d-8144-7c09727f8757": CANONICAL,
    "fd6107e5-2ee5-4b3a-9e7f-40bfd84be1f3": None,  # 智能交互案例1.txt 重复
}


async def main():
    store = get_vector_store()
    collection = f"kb_{PY_KB}"

    async with async_session_factory() as db:
        for doc_id, canonical in DELETIONS.items():
            # ── 1. 迁移 exercises ──
            if canonical:
                moved = (await db.execute(text(
                    "UPDATE exercises SET doc_id=:c WHERE doc_id=:d"
                ), {"c": canonical, "d": doc_id})).rowcount
                if moved:
                    print(f"  🔀 迁移 exercises {moved} 条: {doc_id[:8]} → {canonical[:8]}")

            # ── 2. 收集该 doc 的 ChromaDB 向量 id ──
            entries = await store.get_all_documents(collection)
            vector_ids = [
                e["id"] for e in entries
                if str((e.get("metadata") or {}).get("doc_id", "")).lower() == doc_id.lower()
            ]
            if vector_ids:
                for i in range(0, len(vector_ids), 100):
                    await store.delete_by_ids(collection, vector_ids[i:i + 100])
                print(f"  🗑️  ChromaDB 删除 {len(vector_ids)} 向量: {doc_id[:8]}")

            # ── 3. 删除 DB chunks + document ──
            await db.execute(text("DELETE FROM document_chunks WHERE doc_id=:d"), {"d": doc_id})
            await db.execute(text("DELETE FROM documents WHERE id=:d"), {"d": doc_id})

        await db.commit()
        print("\n✅ 提交完成")

        # ── 4. 验证 ──
        remain = await store.get_all_documents(collection)
        print(f"  ChromaDB 剩余向量: {len(remain)}")


if __name__ == "__main__":
    asyncio.run(main())
