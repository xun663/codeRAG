"""Anthropic Claude provider (stub)."""
from __future__ import annotations

from typing import AsyncGenerator

from app.config import settings
from app.llm.base import BaseLLMProvider


class AnthropicProvider(BaseLLMProvider):
    def __init__(self):
        self.api_key = settings.anthropic_api_key
        self.model = "claude-sonnet-4-20250514"

    async def generate(self, prompt: str, system_prompt: str | None = None, **kwargs) -> str:
        try:
            from anthropic import AsyncAnthropic
            client = AsyncAnthropic(api_key=self.api_key)
            messages = [{"role": "user", "content": prompt}]
            response = await client.messages.create(
                model=self.model,
                max_tokens=kwargs.get("max_tokens", 2048),
                system=system_prompt or "",
                messages=messages,
            )
            return response.content[0].text
        except ImportError:
            # Fallback to OpenAI-compatible if anthropic SDK not available
            from app.llm.openai_provider import OpenAIProvider
            provider = OpenAIProvider()
            return await provider.generate(prompt, system_prompt, **kwargs)

    async def generate_stream(self, prompt: str, system_prompt: str | None = None, **kwargs) -> AsyncGenerator[str, None]:
        try:
            from anthropic import AsyncAnthropic
            client = AsyncAnthropic(api_key=self.api_key)
            messages = [{"role": "user", "content": prompt}]
            async with client.messages.stream(
                model=self.model,
                max_tokens=kwargs.get("max_tokens", 2048),
                system=system_prompt or "",
                messages=messages,
            ) as stream:
                async for text in stream.text_stream:
                    yield text
        except ImportError:
            from app.llm.openai_provider import OpenAIProvider
            provider = OpenAIProvider()
            async for token in provider.generate_stream(prompt, system_prompt, **kwargs):
                yield token

    async def count_tokens(self, text: str) -> int:
        return len(text) // 4
