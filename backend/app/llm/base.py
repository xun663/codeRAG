"""Abstract LLM provider interface."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncGenerator


class BaseLLMProvider(ABC):
    """Abstract base for LLM providers."""

    @abstractmethod
    async def generate(self, prompt: str, system_prompt: str | None = None, **kwargs) -> str:
        """Generate a complete response."""
        ...

    @abstractmethod
    async def generate_stream(
        self, prompt: str, system_prompt: str | None = None, **kwargs
    ) -> AsyncGenerator[str, None]:
        """Generate a streaming response, yielding tokens."""
        ...

    @abstractmethod
    async def count_tokens(self, text: str) -> int:
        """Estimate token count."""
        ...
