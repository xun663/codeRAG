"""Local sentence-transformers embedding."""
from __future__ import annotations

import os

# Force offline mode to prevent HuggingFace network calls (model is cached locally)
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from app.config import settings
from app.embedding.base import BaseEmbeddingModel
from app.utils.device import get_device


class LocalEmbeddingModel(BaseEmbeddingModel):
    _instance = None
    _model = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def _get_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            device = get_device()
            self._model = SentenceTransformer(
                settings.embedding_model,
                device=device,          # ← GPU auto-detected; falls back to CPU
            )
        return self._model

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        import asyncio
        model = self._get_model()
        # Run in thread pool to avoid blocking
        embeddings = await asyncio.to_thread(
            model.encode, texts, batch_size=32, show_progress_bar=False
        )
        return embeddings.tolist()

    async def embed_text(self, text: str) -> list[float]:
        result = await self.embed_texts([text])
        return result[0]

    def get_dimension(self) -> int:
        model = self._get_model()
        return model.get_sentence_embedding_dimension()
