"""按 kb_id 重建知识库索引（清旧 chunk + 重新分块/嵌入/写向量库）。

用法：cd backend && python scripts/reindex_kb.py <kb_id>

用于：分块器/清洗逻辑更新后，需要重跑文档管道让新逻辑生效。

健壮性（避免生产踩坑）：
  - 循环内只使用从 DB 捕获的纯数据（doc_id/title/file_path/mime），
    不持有 ORM 对象——某文档失败触发 db.rollback() 后所有 ORM 对象会过期，
    再访问属性会触发 async 环境的同步 lazy-load → MissingGreenlet 崩溃。
  - 单文档失败只跳过该文档（保留旧 chunk），不中断整批。
"""
from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

from sqlalchemy import select, update

from app.core.documents.pipeline import DocumentPipeline
from app.db.session import async_session_factory
from app.models.document import Document, DocumentChunk
from app.vector_store.factory import get_vector_store


async def _warm_embedding_config(db) -> None:
    """加载 admin 在 UI 配置的运行时 embedding（千问 v3），独立进程无 lifespan。

    不预热会回退到 .env 默认（DeepSeek 无 /embeddings 端点 → 查询嵌入 404）。
    """
    from app.core.monitoring.config_manager import ConfigManager, EMBEDDING_CONFIG_KEY
    from app.embedding.factory import clear_embedding_model_cache
    from app.embedding.runtime_config import set_runtime_embedding_config
    from app.llm.crypto import decrypt

    cfg = await ConfigManager.get_config(db, EMBEDDING_CONFIG_KEY)
    if cfg and cfg.config_value:
        v = cfg.config_value
        set_runtime_embedding_config({
            "provider": v.get("provider", "openai"),
            "base_url": v.get("base_url", ""),
            "model": v.get("model", ""),
            "api_key": decrypt(v.get("api_key_encrypted", "")),
            "dimension": int(v.get("dimension") or 1024),
        })
        clear_embedding_model_cache()
        print(f"🌡️  嵌入运行时配置已加载（{v.get('provider')} / {v.get('model')}）")
    else:
        print("⚠️  未找到运行时 embedding 配置，将用 .env 默认（可能维度不匹配/404）")


async def reindex(kb_id: str) -> None:
    store = get_vector_store()
    collection = f"kb_{kb_id}"

    # 预热运行时 embedding 配置（必须在创建 pipeline / 首次加载 embedding 模型之前）
    async with async_session_factory() as db:
        await _warm_embedding_config(db)
    pipeline = DocumentPipeline()

    async with async_session_factory() as db:
        # 文档/分块即将变更 → 旧门禁结果先失效，避免报告页显示脏指标
        from app.services.kb_service import KBService
        await KBService.invalidate_quality_gate(db, kb_id)
        docs = (await db.execute(select(Document).where(Document.kb_id == kb_id))).scalars().all()
        # 捕获纯数据：避免 rollback 后 ORM 过期对象触发 lazy-load (MissingGreenlet)
        specs = [(d.id, d.title, d.file_path, d.mime_type) for d in docs]
        print(f"📚 {len(specs)} 篇文档")

        total = 0
        for doc_id, title, file_path, mime in specs:
            if not file_path or not Path(file_path).exists():
                print(f"  ⏭️  {title}: file not found（跳过，保留旧 chunk）")
                continue
            try:
                # ① 清旧 chunk（DB + 向量库）
                old = (await db.execute(
                    select(DocumentChunk).where(DocumentChunk.doc_id == doc_id)
                )).scalars().all()
                old_vector_ids = [c.vector_id for c in old if c.vector_id]
                for c in old:
                    await db.delete(c)
                await db.flush()
                if old_vector_ids:
                    await store.delete_by_ids(collection, old_vector_ids)

                # ② 重新走文档管道（解析→清洗→分块→嵌入→索引）
                result = await pipeline.process_file(
                    file_path=str(file_path),
                    kb_id=kb_id,
                    mime_type=mime,
                    doc_id=str(doc_id),
                    doc_title=title,
                )

                # ③ 写回 DB
                for i, c in enumerate(result["chunks"]):
                    chunk_id = c.get("id", str(uuid.uuid4()))
                    db.add(DocumentChunk(
                        id=uuid.UUID(chunk_id),
                        doc_id=doc_id,
                        kb_id=kb_id,
                        chunk_index=i,
                        content=c["content"],
                        content_preview=c["content"][:200],
                        token_count=c.get("token_count", 0),
                        vector_id=chunk_id,
                        chunk_type=c.get("chunk_type", "text"),
                        metadata_json=c.get("metadata", {}),
                    ))
                # 用 UPDATE 语句更新状态（避免触碰可能过期的 ORM 对象）
                await db.execute(
                    update(Document).where(Document.id == doc_id).values(status="indexed")
                )
                await db.flush()
                total += len(result["chunks"])
                print(f"  ✅ {title[:40]:42s} → {len(result['chunks'])} chunks")
            except Exception as e:
                print(f"  ❌ {title}: {e}（跳过，保留旧 chunk）")
                await db.rollback()
                continue

        # 更新 KB 计数器（doc_count/chunk_count），否则报告页显示过期的旧分块数
        from app.services.kb_service import KBService
        await KBService.sync_counters(db, kb_id)

        await db.commit()
        print(f"\n✅ 重建完成，共 {total} chunks（collection={collection}）")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("用法: python scripts/reindex_kb.py <kb_id>")
    asyncio.run(reindex(sys.argv[1]))
