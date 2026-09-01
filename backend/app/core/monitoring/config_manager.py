"""System configuration manager."""
from __future__ import annotations

import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.feedback import SystemConfig

# SystemConfig key under which the admin-configured embedding settings are stored.
EMBEDDING_CONFIG_KEY = "embedding_config"


class ConfigManager:
    @staticmethod
    async def list_config(db: AsyncSession) -> list[SystemConfig]:
        result = await db.execute(select(SystemConfig))
        return result.scalars().all()

    @staticmethod
    async def get_config(db: AsyncSession, key: str) -> SystemConfig | None:
        result = await db.execute(select(SystemConfig).where(SystemConfig.config_key == key))
        return result.scalar_one_or_none()

    @staticmethod
    async def update_config(db: AsyncSession, key: str, value: dict, user) -> SystemConfig:
        result = await db.execute(select(SystemConfig).where(SystemConfig.config_key == key))
        config = result.scalar_one_or_none()

        if config:
            config.config_value = value
            config.updated_by = user.id
        else:
            config = SystemConfig(
                id=uuid.uuid4(),
                config_key=key,
                config_value=value,
                updated_by=user.id,
            )
            db.add(config)
        await db.flush()
        return config

    @staticmethod
    async def test_llm(config: dict) -> dict:
        """Test the *submitted* (not-yet-saved) LLM config directly."""
        try:
            from app.llm.openai_provider import OpenAIProvider
            llm = OpenAIProvider(
                api_key=config.get("api_key"),
                base_url=config.get("base_url"),
                model=config.get("model"),
            )
            response = await llm.generate("Hello! Respond with 'OK' if you can read this.")
            return {"success": True, "response": response[:100]}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ── Embedding config ────────────────────────────────────────

    @staticmethod
    async def get_embedding_config(db: AsyncSession) -> dict:
        """读 embedding 配置（api_key 脱敏）。未配置时返回当前 .env 生效值供前端回填。"""
        config = await ConfigManager.get_config(db, EMBEDDING_CONFIG_KEY)
        if config and config.config_value:
            v = config.config_value
            return {
                "provider": v.get("provider", "local"),
                "base_url": v.get("base_url", ""),
                "model": v.get("model", ""),
                "dimension": int(v.get("dimension") or 1024),
                "has_key": bool(v.get("api_key_encrypted")),
            }
        from app.embedding.runtime_config import get_runtime_embedding_config
        rc = get_runtime_embedding_config()
        return {
            "provider": rc.get("provider", "local"),
            "base_url": rc.get("base_url", ""),
            "model": rc.get("model", ""),
            "dimension": int(rc.get("dimension") or 1024),
            "has_key": bool(rc.get("api_key")),
        }

    @staticmethod
    async def update_embedding_config(db: AsyncSession, value: dict, user) -> dict:
        """保存 embedding 配置：维度校验 → 加密 api_key → 落库 → 刷新 runtime + 清缓存。"""
        from app.embedding.factory import clear_embedding_model_cache
        from app.embedding.runtime_config import set_runtime_embedding_config
        from app.llm.crypto import decrypt, encrypt

        new_dim = int(value.get("dimension") or 1024)

        # 1. 维度校验：与现有向量库维度不兼容则阻止
        existing_dim = await ConfigManager._existing_vector_dimension()
        if existing_dim and existing_dim != new_dim:
            from app.exceptions import ForbiddenException
            raise ForbiddenException(
                f"嵌入模型维度不兼容：现有向量库为 {existing_dim} 维，新配置为 {new_dim} 维。"
                "需先重建全库向量，或选择同维度模型（bge-m3 与千问 v3 均为 1024 维）"
            )

        # 2. api_key：填写则加密，留空保留旧密文
        api_key = value.get("api_key", "")
        if api_key:
            api_key_enc = encrypt(api_key)
        else:
            old = await ConfigManager.get_config(db, EMBEDDING_CONFIG_KEY)
            api_key_enc = old.config_value.get("api_key_encrypted", "") if old and old.config_value else ""

        config_value = {
            "provider": value.get("provider", "local"),
            "base_url": value.get("base_url", ""),
            "model": value.get("model", ""),
            "dimension": new_dim,
            "api_key_encrypted": api_key_enc,
        }
        await ConfigManager.update_config(db, EMBEDDING_CONFIG_KEY, config_value, user)

        # 3. 立即生效：刷新运行时缓存 + 失效已构造的模型
        set_runtime_embedding_config({
            "provider": config_value["provider"],
            "base_url": config_value["base_url"],
            "model": config_value["model"],
            "api_key": decrypt(api_key_enc),
            "dimension": new_dim,
        })
        clear_embedding_model_cache()

        return await ConfigManager.get_embedding_config(db)

    @staticmethod
    async def _existing_vector_dimension() -> int | None:
        """遍历 ChromaDB `kb_*` collections，取第一个非空 collection 的向量维度。"""
        from app.vector_store.factory import get_vector_store
        store = get_vector_store()
        try:
            collections = store.client.list_collections()
        except Exception:
            return None
        for col in collections:
            try:
                name = col.name if hasattr(col, "name") else str(col)
                if not name.startswith("kb_"):
                    continue
                collection = store.client.get_collection(name=name)
                peek = collection.peek(limit=1)
                embeddings = peek.get("embeddings") if peek else None
                if embeddings is not None and len(embeddings) > 0:
                    return len(embeddings[0])
            except Exception:
                continue
        return None
