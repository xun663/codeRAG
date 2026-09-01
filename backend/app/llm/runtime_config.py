"""Runtime LLM configuration cache.

`get_llm_provider()` is a synchronous function with many call sites that cannot
await the DB. This module holds a process-level snapshot of the admin-configured
LLM settings (stored in the `system_config` table), loaded at startup and
refreshed synchronously when the admin saves new values.

Priority: runtime config (admin set in UI) > static `.env` settings.
"""
from __future__ import annotations

from app.config import settings

_runtime_config: dict | None = None  # {provider, base_url, model, api_key}


def get_runtime_config() -> dict:
    """Return effective LLM config: cached runtime value with .env fallbacks."""
    cfg = _runtime_config or {}
    return {
        "provider": cfg.get("provider") or settings.default_llm_provider,
        "base_url": cfg.get("base_url") or settings.openai_api_base,
        "model": cfg.get("model") or settings.openai_model,
        "api_key": cfg.get("api_key") or settings.effective_api_key,
    }


def set_runtime_config(cfg: dict) -> None:
    """Replace the cached runtime LLM config (called after admin saves)."""
    global _runtime_config
    _runtime_config = {
        "provider": cfg.get("provider") or "openai",
        "base_url": cfg.get("base_url") or "",
        "model": cfg.get("model") or "",
        "api_key": cfg.get("api_key") or "",
    }


def clear_runtime_config() -> None:
    """Reset cache to fall back entirely on .env settings."""
    global _runtime_config
    _runtime_config = None
