#!/usr/bin/env python3
"""用生产模型 bge-m3 从 DB 重建 Chroma 集合（幂等，可安全重跑）。

背景：
  清理 Chroma 重复后实测发现，当前集合中 id=chunk id 的"当前副本"
  可能是旧模型（bge-small-zh 时代）嵌入的，而清理掉的副本反而
  是 bge-m3 嵌入的 → 查询（bge-m3）与索引模型不一致，召回受损。
  本脚本从 DB 重新嵌入全部 chunk，保证 索引模型 == 查询模型。

设计：
  - 只动 Chroma，不动 DB（DB 是 source of truth）
  - chroma id = str(DocumentChunk.id)（与 vector_id 一致的混合 ID 方案）
  - metadatas 与文档管道一致：doc_title / kb_id / doc_id / chunk_type / token_count
  - 删除集合 → 重建 → 全量写入，幂等

用法：
    cd backend && PYTHONUTF8=1 python scripts/rebuild_collections.py
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.config import settings
from app.db.session import async_session_factory
from app.models.document import Document, DocumentChunk
from app.embedding.factory import get_embedding_model
from app.vector_store.factory import get_vector_store

KBS = {
    "Python": "126739c2-e665-4e69-ad59-14218fe5c95d",
    "Java": "34139461-a995-4f77-86bd-ced21883929d",
}

# 记忆: 长短文本混合时 batch_size=32 有 40x padding 退化 → 用 batch_size=1
EMBED_BATCH = 1


async def main():
    store = get_vector_store()
    emb = get_embedding_model()
    print(f"embedding model: {settings.embedding_model}")

    async with async_session_factory() as db:
        for label, kb_id in KBS.items():
            collection = f"kb_{kb_id}"
            print(f"\n{'=' * 70}\n  {label} ({kb_id})\n{'=' * 70}")

            # 1) Load chunks + doc titles
            chunks = (
                (await db.execute(
                    select(DocumentChunk).where(DocumentChunk.kb_id == kb_id)
                ))
                .scalars()
                .all()
            )
            docs = (
                (await db.execute(select(Document).where(Document.kb_id == kb_id)))
                .scalars()
                .all()
            )
            title_map = {str(d.id): d.title for d in docs}
            print(f"  chunks: {len(chunks)}, docs: {len(docs)}")

            # 2) Embed — bypass embed_texts() 硬编码的 batch_size=32（长短混合 padding 40x 退化），
            #    直接 model.encode(batch_size=1)
            # 标题增强：embedding 文本 = "doc_title —— content"，让标题词参与语义对齐；
            # 但 ChromaDB 存储的 documents 仍为纯 content（不污染展示/BM25/引用）。
            contents = [c.content for c in chunks]
            embed_texts = [
                f"{title_map.get(str(c.doc_id), '')} —— {c.content}" for c in chunks
            ]
            t0 = time.monotonic()
            model = emb._get_model()  # noqa: SLF001 — LocalEmbeddingModel singleton
            import asyncio
            embeddings = await asyncio.to_thread(
                model.encode, embed_texts, batch_size=1, show_progress_bar=True
            )
            print(f"  embedded {len(embeddings)} chunks (title-enhanced) in {time.monotonic() - t0:.0f}s")

            # 3) Rebuild collection
            await store.delete_collection(collection)
            await store.create_collection(collection)
            ids = [str(c.id) for c in chunks]
            metadatas = [
                {
                    "doc_id": str(c.doc_id),
                    "doc_title": title_map.get(str(c.doc_id), ""),
                    "kb_id": kb_id,
                    "chunk_type": c.chunk_type or "text",
                    "token_count": c.token_count or 0,
                }
                for c in chunks
            ]
            # batch add in chunks of 500
            B = 500
            for i in range(0, len(ids), B):
                await store.add_vectors(
                    collection_name=collection,
                    ids=ids[i : i + B],
                    embeddings=embeddings[i : i + B],
                    documents=contents[i : i + B],
                    metadatas=metadatas[i : i + B],
                )
                print(f"  added {min(i + B, len(ids))}/{len(ids)}")

            stats = await store.get_collection_stats(collection)
            print(f"  ✅ collection '{collection}' → {stats['count']} entries")


if __name__ == "__main__":
    asyncio.run(main())
