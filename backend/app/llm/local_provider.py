"""Local LLM provider (Ollama-compatible)."""
from __future__ import annotations

from typing import AsyncGenerator

import httpx

from app.config import settings
from app.llm.base import BaseLLMProvider


class LocalProvider(BaseLLMProvider):
    def __init__(self):
        self.base_url = settings.local_llm_url
        self.model = settings.local_llm_model

    async def generate(self, prompt: str, system_prompt: str | None = None, **kwargs) -> str:
        async with httpx.AsyncClient(timeout=120) as client:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            response = await client.post(
                f"{self.base_url}/api/chat",
                json={"model": self.model, "messages": messages, "stream": False},
            )
            data = response.json()
            return data.get("message", {}).get("content", "")

    async def generate_stream(self, prompt: str, system_prompt: str | None = None, **kwargs) -> AsyncGenerator[str, None]:
        async with httpx.AsyncClient(timeout=120) as client:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            async with client.stream(
                "POST",
                f"{self.base_url}/api/chat",
                json={"model": self.model, "messages": messages, "stream": True},
            ) as response:
                async for line in response.aiter_lines():
                    if line.strip():
                        try:
                            import json
                            data = json.loads(line)
                            if data.get("message", {}).get("content"):
                                yield data["message"]["content"]
                        except json.JSONDecodeError:
                            continue

    async def count_tokens(self, text: str) -> int:
        return len(text) // 4
