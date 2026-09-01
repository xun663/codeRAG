#!/usr/bin/env python3
"""评估 KB 状态 — DB chunks vs Chroma 条目一致性审计。

回答四个问题：
  1) DB document_chunks 里每个 KB 有多少 chunks（是否有 DB 级重复）
  2) Chroma 集合里每个 KB 有多少条目（是否有多余/重复向量）
  3) DB chunk 与 Chroma 条目的对应关系（content 层面）
  4) DocumentChunk.vector_id 是否被填充（旧设计痕迹）

用法：
    cd backend && PYTHONUTF8=1 python scripts/assess_kb_state.py
"""
from __future__ import annotations

import asyncio
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, func

from app.db.session import async_session_factory
from app.models.document import Document, DocumentChunk
from app.vector_store.factory import get_vector_store

KB = {
    "Python": "126739c2-e665-4e69-ad59-14218fe5c95d",
    "Java": "34139461-a995-4f77-86bd-ced21883929d",
}


async def main():
    store = get_vector_store()

    async with async_session_factory() as db:
        for label, kb_id in KB.items():
            print(f"\n{'=' * 70}")
            print(f"  KB: {label}  ({kb_id})")
            print(f"{'=' * 70}")

            # ── DB state ──────────────────────────────────────────
            docs = (
                await db.execute(select(Document.id, Document.title).where(Document.kb_id == kb_id))
            ).all()
            print(f"\n  [DB] documents: {len(docs)}")
            for did, title in docs[:8]:
                print(f"      - {title[:60]}")
            if len(docs) > 8:
                print(f"      ... ({len(docs) - 8} more)")

            chunks = (
                await db.execute(
                    select(DocumentChunk)
                    .where(DocumentChunk.kb_id == kb_id)
                )
            ).scalars().all()
            print(f"  [DB] chunks: {len(chunks)}")

            # DB-level duplicate detection: same (doc_id, content)
            content_counts = Counter((str(c.doc_id), c.content[:80]) for c in chunks)
            dups = {k: v for k, v in content_counts.items() if v > 1}
            print(f"  [DB] chunks duplicated by (doc_id, content[:80]): {len(dups)} groups → {sum(dups.values())} rows")

            # vector_id population
            n_vector_id = sum(1 for c in chunks if c.vector_id)
            print(f"  [DB] rows with vector_id populated: {n_vector_id}/{len(chunks)}")
            if chunks and chunks[0].vector_id:
                print(f"      sample vector_id: {chunks[0].vector_id[:36]}...  (id: {str(chunks[0].id)[:8]}...)")

            # ── Chroma state ──────────────────────────────────────
            collection = f"kb_{kb_id}"
            entries = await store.get_all_documents(collection)
            print(f"\n  [Chroma] entries: {len(entries)}  (DB chunks: {len(chunks)})")

            # Chroma-side stats
            ids = [e["id"] for e in entries]
            unique_ids = len(set(ids))
            print(f"  [Chroma] unique ids: {unique_ids}  → 重复 ID 条目: {len(ids) - unique_ids}")

            doc_ids_in_chroma = Counter(
                str((e.get("metadata") or {}).get("doc_id", "")) for e in entries
            )
            db_doc_ids = {str(d[0]) for d in docs}
            orphan_docs = {d: n for d, n in doc_ids_in_chroma.items() if d and d not in db_doc_ids}
            print(f"  [Chroma] doc_id 不在 DB 的条目: {sum(orphan_docs.values())} ({len(orphan_docs)} 个孤儿文档)")
            if orphan_docs:
                print(f"      孤儿文档 ID 示例: {list(orphan_docs.items())[:3]}")

            # content-level duplicate detection in chroma
            content_counts_c = Counter((str((e.get("metadata") or {}).get("doc_id", "")), (e.get("document") or "")[:80]) for e in entries)
            dups_c = {k: v for k, v in content_counts_c.items() if v > 1}
            print(f"  [Chroma] (doc_id, content[:80]) 重复组: {len(dups_c)} 组 → {sum(dups_c.values())} 条目")

            # ID-space alignment: are chroma ids == DB chunk ids?
            db_chunk_ids = {str(c.id) for c in chunks}
            id_set = set(ids)
            overlap = id_set & db_chunk_ids
            print(f"  [ID空间] chroma id ∩ DB chunk id: {len(overlap)} 个相同")
            # chroma ids that match DB vector_id (current index)
            db_vector_ids = {c.vector_id for c in chunks if c.vector_id}
            v_overlap = id_set & db_vector_ids
            print(f"  [ID空间] chroma id ∩ DB vector_id: {len(v_overlap)} 个相同")

            # how many DB chunk ids missing from chroma
            missing = len(db_chunk_ids - id_set)
            print(f"  [ID空间] DB chunk id 不在 chroma 中: {missing}/{len(db_chunk_ids)}")


if __name__ == "__main__":
    asyncio.run(main())
