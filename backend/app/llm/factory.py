"""LLM provider factory."""
from __future__ import annotations

from app.config import settings
from app.llm.base import BaseLLMProvider
from app.llm.runtime_config import get_runtime_config


class NoopProvider(BaseLLMProvider):
    """Fallback provider that returns placeholder responses when no LLM is configured."""
    async def generate(self, prompt: str, system_prompt: str | None = None, **kwargs) -> str:
        return "LLM provider is not configured. Please set OPENAI_API_KEY in your .env file."
    async def generate_stream(self, prompt: str, system_prompt: str | None = None, **kwargs):
        yield "LLM provider is not configured."
    async def count_tokens(self, text: str) -> int:
        return len(text) // 4


def get_llm_provider(provider: str | None = None) -> BaseLLMProvider:
    """Get LLM provider instance by name. Falls back to noop if unavailable or unconfigured."""
    provider = provider or settings.default_llm_provider

    if provider == "openai":
        runtime = get_runtime_config()
        api_key = runtime.get("api_key") or settings.effective_api_key
        if not api_key or api_key.startswith("sk-xxx"):
            return NoopProvider()
        try:
            from app.llm.openai_provider import OpenAIProvider
            return OpenAIProvider(
                api_key=api_key,
                base_url=runtime.get("base_url") or settings.openai_api_base,
                model=runtime.get("model") or settings.openai_model,
            )
        except Exception:
            return NoopProvider()

    if provider == "anthropic":
        try:
            from app.llm.anthropic_provider import AnthropicProvider
            return AnthropicProvider()
        except Exception:
            return NoopProvider()

    if provider == "local":
        try:
            from app.llm.local_provider import LocalProvider
            return LocalProvider()
        except Exception:
            return NoopProvider()

    raise ValueError(f"Unknown LLM provider: {provider}")
