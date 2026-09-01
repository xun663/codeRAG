#!/usr/bin/env python3
"""Clean duplicate entries from ChromaDB — keep only DB-referenced vectors.

ChromaDB 中可能存在重复导入导致的多余向量。此脚本：
1. 扫描 ChromaDB 中每个 KB collection
2. 对比 DB DocumentChunk.vector_id
3. 删除 ChromaDB 中多余副本

Usage:
    cd backend && PYTHONUTF8=1 python scripts/cleanup_chromadb_dups.py
"""
from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import select

from app.db.session import async_session_factory
from app.models.document import DocumentChunk
from app.vector_store.factory import get_vector_store


KB_IDS = {
    "python": ("126739c2-e665-4e69-ad59-14218fe5c95d", "Python KB"),
    "java": ("34139461-a995-4f77-86bd-ced21883929d", "Java KB"),
}


async def main():
    store = get_vector_store()

    for name, (kb_id, label) in KB_IDS.items():
        collection = f"kb_{kb_id}"
        print(f"\n{'=' * 60}")
        print(f"  {label} (collection={collection})")

        # 1) Get DB vector IDs
        async with async_session_factory() as db:
            chunks = (
                (await db.execute(
                    select(DocumentChunk).where(DocumentChunk.kb_id == uuid.UUID(kb_id))
                ))
                .scalars()
                .all()
            )
            db_vector_ids = set(c.vector_id for c in chunks if c.vector_id)
            print(f"  DB DocumentChunks: {len(chunks)}, with vector_id: {len(db_vector_ids)}")

        # 2) Get ChromaDB IDs
        chroma_docs = await store.get_all_documents(collection)
        chroma_ids = set(d["id"] for d in chroma_docs)
        print(f"  ChromaDB entries:  {len(chroma_docs)}")

        # 3) Find ChromaDB IDs not in DB
        orphan_ids = chroma_ids - db_vector_ids
        orphan_ids_list = list(orphan_ids)

        if not orphan_ids_list:
            print(f"  ✅ No orphans found — ChromaDB is clean.")
            continue

        print(f"  Orphan entries:    {len(orphan_ids_list)}")

        # 4) Delete orphans in batches
        BATCH = 100
        deleted = 0
        for i in range(0, len(orphan_ids_list), BATCH):
            batch = orphan_ids_list[i : i + BATCH]
            await store.delete_by_ids(collection, batch)
            deleted += len(batch)
            print(f"    Deleted {deleted}/{len(orphan_ids_list)}...")

        # 5) Verify
        remaining = await store.get_all_documents(collection)
        print(f"  ✅ After cleanup: {len(remaining)} entries in ChromaDB")
        print(f"     (expected ~{len(db_vector_ids)} for matching DB)")


if __name__ == "__main__":
    asyncio.run(main())
