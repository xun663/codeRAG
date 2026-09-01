"""Abstract chunker interface."""
from __future__ import annotations

from abc import ABC, abstractmethod


class BaseChunker(ABC):
    """Abstract base for text chunkers."""

    @abstractmethod
    async def split(self, text: str, metadata: dict | None = None) -> list[dict]:
        """Split text into chunks. Each chunk is {content, chunk_type, metadata, token_count}."""
        ...

    def estimate_tokens(self, text: str) -> int:
        """Rough token count estimation."""
        return max(1, len(text) // 4)
