"""Runtime embedding configuration cache.

`get_embedding_model()` is a synchronous factory with many call sites that
cannot await the DB. This module holds a process-level snapshot of the
admin-configured embedding settings (stored in the `system_config` table under
key `embedding_config`), loaded at startup and refreshed when the admin saves.

Priority: runtime config (admin set in UI) > static `.env` settings.
"""
from __future__ import annotations

from app.config import settings

_runtime_config: dict | None = None  # {provider, base_url, model, api_key, dimension}


def get_runtime_embedding_config() -> dict:
    """Return effective embedding config: cached runtime value with .env fallbacks."""
    cfg = _runtime_config or {}
    return {
        "provider": cfg.get("provider") or settings.default_embedding_provider,
        "base_url": cfg.get("base_url") or settings.openai_api_base,
        "model": cfg.get("model") or settings.openai_embedding_model,
        "api_key": cfg.get("api_key") or settings.openai_api_key,
        "dimension": cfg.get("dimension") or 1024,
    }


def set_runtime_embedding_config(cfg: dict) -> None:
    """Replace the cached runtime embedding config (called after admin saves)."""
    global _runtime_config
    _runtime_config = {
        "provider": cfg.get("provider") or "local",
        "base_url": cfg.get("base_url") or "",
        "model": cfg.get("model") or "",
        "api_key": cfg.get("api_key") or "",
        "dimension": int(cfg.get("dimension") or 1024),
    }


def clear_runtime_embedding_config() -> None:
    """Reset cache to fall back entirely on .env settings."""
    global _runtime_config
    _runtime_config = None
