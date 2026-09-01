#!/usr/bin/env python3
"""清洗 Java KB 导航污染并重建索引。

流程（安全，分两阶段）:
  Stage A: 对每个 DB 文档读原始文件 → W3SchoolsNavCleaner 清洗 → 重新分块 →
           删除旧 DB chunks → 写入新 chunks（新 uuid，保持与 DB 一致）
  Stage B: 从 DB 读清洗后的 chunk → 标题增强 embedding → 重建 ChromaDB collection
           （chunk_id = DocumentChunk.id，稳定；与 rebuild_collections.py 一致）

注意: 清洗 + 重分块会改变 chunk 粒度 → 评估数据的 ground_truth_chunk_ids 失效。
      文档级指标（relevant_doc_ids）不受影响。评估 GT 需后续按新 chunk 重标。

用法:
    cd backend && PYTHONUTF8=1 python scripts/reindex_java_clean_nav.py
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from sqlalchemy import delete, select, text

from app.db.session import async_session_factory
from app.models.document import Document, DocumentChunk
from app.core.documents.chunkers.hybrid import HybridChunker
from app.core.documents.cleaners.rules import W3SchoolsNavCleaner
from app.embedding.factory import get_embedding_model
from app.vector_store.factory import get_vector_store

JAVA_KB = "34139461-a995-4f77-86bd-ced21883929d"
COLLECTION = f"kb_{JAVA_KB}"
EMBED_BATCH = 1


async def stage_a_clean_and_chunk():
    """清洗原始文件 + 重分块，更新 DB chunks。"""
    cleaner = W3SchoolsNavCleaner()
    chunker = HybridChunker()

    async with async_session_factory() as db:
        docs = (
            (await db.execute(
                select(Document).where(Document.kb_id == JAVA_KB)
            ))
            .scalars()
            .all()
        )
        print(f"\n=== Stage A: 清洗 + 重分块 ({len(docs)} docs) ===")
        total_chunks = 0
        for d in docs:
            fp = Path(d.file_path)
            if not fp.exists():
                print(f"  ⏭️  {d.title}: 文件缺失")
                continue
            raw = fp.read_text(encoding="utf-8", errors="replace")
            cleaned = await cleaner.clean(raw, {"source_file": fp.name})

            chunks = await chunker.split(cleaned, {
                "file_extension": fp.suffix, "language": "markdown",
                "mime_type": "text/markdown", "source_file": fp.name,
            })

            # 删除旧 chunks
            await db.execute(delete(DocumentChunk).where(DocumentChunk.doc_id == d.id))
            await db.flush()

            # 写新 chunks
            for i, c in enumerate(chunks):
                cid = uuid.uuid4()
                db.add(DocumentChunk(
                    id=cid, doc_id=d.id, kb_id=JAVA_KB, chunk_index=i,
                    content=c["content"], content_preview=c["content"][:200],
                    token_count=c.get("token_count", 0),
                    vector_id=str(cid), chunk_type=c.get("chunk_type", "text"),
                    metadata_json=c.get("metadata", {}),
                ))
            await db.flush()
            total_chunks += len(chunks)
            print(f"  ✅ {d.title:32s} → {len(chunks)} chunks")

        await db.commit()
        print(f"  Stage A 完成: {total_chunks} chunks 写入 DB")


async def stage_b_rebuild_chroma():
    """从 DB 清洗后的 chunk 重建 ChromaDB（标题增强 embedding）。"""
    store = get_vector_store()
    emb = get_embedding_model()

    async with async_session_factory() as db:
        chunks = (
            (await db.execute(
                select(DocumentChunk).where(DocumentChunk.kb_id == JAVA_KB)
            ))
            .scalars()
            .all()
        )
        docs = (
            (await db.execute(select(Document).where(Document.kb_id == JAVA_KB)))
            .scalars()
            .all()
        )
        title_map = {str(d.id): d.title for d in docs}
        print(f"\n=== Stage B: 重建 ChromaDB ({len(chunks)} chunks) ===")

        contents = [c.content for c in chunks]
        embed_texts = [
            f"{title_map.get(str(c.doc_id), '')} —— {c.content}" for c in chunks
        ]
        model = emb._get_model()  # noqa: SLF001
        import asyncio as _aio
        embeddings = await _aio.to_thread(
            model.encode, embed_texts, batch_size=EMBED_BATCH, show_progress_bar=True
        )

        await store.delete_collection(COLLECTION)
        await store.create_collection(COLLECTION)
        ids = [str(c.id) for c in chunks]
        metadatas = [
            {
                "doc_id": str(c.doc_id),
                "doc_title": title_map.get(str(c.doc_id), ""),
                "kb_id": JAVA_KB,
                "chunk_type": c.chunk_type or "text",
                "token_count": c.token_count or 0,
            }
            for c in chunks
        ]
        B = 500
        for i in range(0, len(ids), B):
            await store.add_vectors(
                collection_name=COLLECTION,
                ids=ids[i:i + B],
                embeddings=embeddings[i:i + B],
                documents=contents[i:i + B],
                metadatas=metadatas[i:i + B],
            )
            print(f"  added {min(i + B, len(ids))}/{len(ids)}")

        stats = await store.get_collection_stats(COLLECTION)
        print(f"  ✅ ChromaDB → {stats['count']} entries")


async def main():
    await stage_a_clean_and_chunk()
    await stage_b_rebuild_chroma()


if __name__ == "__main__":
    asyncio.run(main())
