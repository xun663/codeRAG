"""OpenAI embedding model."""
from __future__ import annotations

from openai import AsyncOpenAI

from app.config import settings
from app.embedding.base import BaseEmbeddingModel


class OpenAIEmbeddingModel(BaseEmbeddingModel):
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        dimension: int = 1536,
    ):
        self.client = AsyncOpenAI(
            api_key=api_key or settings.openai_api_key,
            base_url=base_url or settings.openai_api_base,
        )
        self.model = model or settings.openai_embedding_model
        self._dimension = dimension

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        # 千问 text-embedding-v3 单次请求最多 10 条（超出返回 400 batch size invalid）。
        # 分批调用后按 index 排序拼接，保证返回顺序与输入一致。
        batch_size = 10
        results: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            response = await self.client.embeddings.create(
                model=self.model,
                input=batch,
            )
            ordered = sorted(response.data, key=lambda d: d.index)
            results.extend(d.embedding for d in ordered)
        return results

    async def embed_text(self, text: str) -> list[float]:
        result = await self.embed_texts([text])
        return result[0]

    def get_dimension(self) -> int:
        return self._dimension
