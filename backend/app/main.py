"""FastAPI application entry point."""
from __future__ import annotations

# ── UTF-8 Encoding Fix (before any other imports that may print) ──
import io as _io
import os as _os
import sys as _sys

# Force UTF-8 for all I/O — fixes Windows GBK console encoding issues
_os.environ.setdefault("PYTHONUTF8", "1")
_os.environ.setdefault("PYTHONIOENCODING", "utf-8")
if hasattr(_sys.stdout, "reconfigure"):
    try:
        _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
# Wrap stdout for safety: never crash on emoji/CJK characters
_sys.stdout = _io.TextIOWrapper(
    _sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True
)

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.exceptions import AppException, app_exception_handler
from app.api.v1.router import api_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: startup / shutdown events."""
    # Startup
    from app.db.session import engine
    # NOTE: DB tables are managed via Alembic migrations:
    #   cd backend && alembic upgrade head
    # The create_all below is kept as a dev convenience fallback
    # for first-time setup but is no longer the primary mechanism.
    if settings.environment == "development":
        from app.models.base import Base
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    # Load the active LLM profile (if any) so the runtime cache is warm
    try:
        from app.db.session import async_session_factory
        from app.services.llm_profile_service import LLMProfileService
        async with async_session_factory() as db:
            active = await LLMProfileService.get_active_profile(db)
            if active:
                from app.llm.runtime_config import set_runtime_config
                set_runtime_config(active)
    except Exception:
        pass  # 启动加载失败不阻断：回退 .env 配置

    # Load the admin-configured embedding settings (if any) so the runtime cache is warm
    try:
        from app.core.monitoring.config_manager import ConfigManager, EMBEDDING_CONFIG_KEY
        from app.db.session import async_session_factory
        from app.embedding.runtime_config import set_runtime_embedding_config
        from app.llm.crypto import decrypt
        async with async_session_factory() as db:
            cfg = await ConfigManager.get_config(db, EMBEDDING_CONFIG_KEY)
            if cfg and cfg.config_value:
                v = cfg.config_value
                set_runtime_embedding_config({
                    "provider": v.get("provider", "local"),
                    "base_url": v.get("base_url", ""),
                    "model": v.get("model", ""),
                    "api_key": decrypt(v.get("api_key_encrypted", "")),
                    "dimension": int(v.get("dimension") or 1024),
                })
    except Exception:
        pass  # 启动加载失败不阻断：回退 .env 配置
    yield
    # Shutdown
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="CodeRAG API",
        description="RAG-based programming learning knowledge base and Q&A system",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Exception handlers
    app.add_exception_handler(AppException, app_exception_handler)

    # Routes
    app.include_router(api_router)

    @app.get("/health", tags=["health"])
    async def health_check():
        """Health check with dependency status (DB / Redis / ChromaDB)."""
        from app.core.monitoring.tracker import MetricsTracker
        from app.db.session import async_session_factory

        async with async_session_factory() as db:
            health = await MetricsTracker.get_health(db)
        return {
            "status": health["status"],
            "version": "0.1.0",
            "checks": health["checks"],
        }

    return app


app = create_app()
