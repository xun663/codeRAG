"""Embedding model factory."""
from __future__ import annotations

from app.config import settings
from app.embedding.base import BaseEmbeddingModel
from app.embedding.runtime_config import get_runtime_embedding_config

# 模块级缓存：允许 clear_embedding_model_cache() 在切换配置后失效重建
_model_cache: BaseEmbeddingModel | None = None


class NoopEmbedding(BaseEmbeddingModel):
    """Fallback embedding that returns random vectors."""
    _dim = 384

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        import random
        return [[random.random() for _ in range(self._dim)] for _ in texts]

    async def embed_text(self, text: str) -> list[float]:
        r = await self.embed_texts([text])
        return r[0]

    def get_dimension(self) -> int:
        return self._dim


def get_embedding_model(provider: str | None = None) -> BaseEmbeddingModel:
    """Get embedding model instance, honoring the admin-configured runtime config."""
    global _model_cache
    if _model_cache is not None:
        return _model_cache

    runtime = get_runtime_embedding_config()
    provider = provider or runtime.get("provider") or settings.default_embedding_provider

    if provider == "openai":
        try:
            from app.embedding.openai_embedding import OpenAIEmbeddingModel
            _model_cache = OpenAIEmbeddingModel(
                api_key=runtime.get("api_key") or settings.openai_api_key,
                base_url=runtime.get("base_url") or settings.openai_api_base,
                model=runtime.get("model") or settings.openai_embedding_model,
                dimension=int(runtime.get("dimension") or 1536),
            )
            return _model_cache
        except Exception:
            return NoopEmbedding()

    # Default: local sentence-transformers
    try:
        from app.embedding.local_embedding import LocalEmbeddingModel
        _model_cache = LocalEmbeddingModel()
        return _model_cache
    except Exception:
        return NoopEmbedding()


def clear_embedding_model_cache() -> None:
    """Drop the cached model instance so the next call rebuilds with new config."""
    global _model_cache
    _model_cache = None
