"""Abstract document parser."""
from __future__ import annotations

from abc import ABC, abstractmethod


class BaseParser(ABC):
    """Abstract base for document parsers."""

    @abstractmethod
    async def parse(self, file_path: str) -> str:
        """Parse a file and return its text content."""
        ...

    @abstractmethod
    async def supports(self, mime_type: str) -> bool:
        """Check if this parser supports the given mime type."""
        ...
