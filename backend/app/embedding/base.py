"""Abstract embedding model interface."""
from __future__ import annotations

from abc import ABC, abstractmethod


class BaseEmbeddingModel(ABC):
    """Abstract base for embedding models."""

    @abstractmethod
    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of texts."""
        ...

    @abstractmethod
    async def embed_text(self, text: str) -> list[float]:
        """Embed a single text."""
        ...

    @abstractmethod
    def get_dimension(self) -> int:
        """Get embedding dimension."""
        ...
