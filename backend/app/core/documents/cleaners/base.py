"""Abstract base class for text cleaners."""
from __future__ import annotations

from abc import ABC, abstractmethod


class BaseCleaner(ABC):
    """Abstract base for a single text cleaning rule.

    Each cleaner implements one focused cleaning operation.
    The ``name`` property identifies it in logs and statistics.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable cleaner name (e.g. ``"unicode_sanitizer"``)."""
        ...

    @abstractmethod
    async def clean(self, text: str, metadata: dict | None = None) -> str:
        """Apply one cleaning operation and return the cleaned text."""
        ...

    async def __call__(self, text: str, metadata: dict | None = None) -> str:
        return await self.clean(text, metadata)
