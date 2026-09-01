"""Application configuration via pydantic-settings."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Application ──────────────────────────────────────────────
    environment: Literal["development", "production", "test"] = "development"
    debug: bool = True
    log_level: str = "INFO"
    secret_key: str = "dev-secret-key-change-in-production"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 7

    # ── Database ─────────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://coderag:coderag123@localhost:5432/coderag"
    database_url_sync: str = "postgresql://coderag:coderag123@localhost:5432/coderag"

    # ── Redis ────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # ── ChromaDB ─────────────────────────────────────────────────
    chroma_host: str = "localhost"
    chroma_port: int = 8000
    chroma_persist_path: str = "./data/chroma_db"

    # ── Data Cleaning ──────────────────────────────────────────
    cleaning_enabled: bool = True
    cleaning_normalize_unicode: bool = True
    cleaning_remove_html_residue: bool = True
    cleaning_normalize_whitespace: bool = True
    cleaning_filter_noise: bool = True
    cleaning_deduplicate_paragraphs: bool = True

    # ── Upload ───────────────────────────────────────────────────
    upload_dir: str = "./data/uploads"
    max_upload_size_mb: int = 50

    # ── CORS ─────────────────────────────────────────────────────
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    # ── LLM ──────────────────────────────────────────────────────
    fernet_key: str = ""       # Fernet key for encrypting stored LLM API keys; falls back to secret_key
    default_llm_provider: Literal["openai", "anthropic", "local"] = "openai"
    llm_api_key: str = ""       # Generic key, read from system env (setx LLM_API_KEY)
    openai_api_key: str = ""    # Provider-specific key
    openai_api_base: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    anthropic_api_key: str = ""
    local_llm_url: str = "http://localhost:11434"
    local_llm_model: str = "llama3"

    @property
    def effective_api_key(self) -> str:
        """Get valid API key: LLM_API_KEY env > registry > OPENAI_API_KEY env."""
        # 1. Check LLM_API_KEY from .env / process env
        if self.llm_api_key and not self.llm_api_key.startswith("sk-xxx"):
            return self.llm_api_key
        # 2. Read from Windows registry (setx LLM_API_KEY)
        try:
            import winreg
            reg = winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_READ)
            i = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(reg, i)
                    if name.upper().replace("SETX ", "").strip() == "LLM_API_KEY":
                        if value and not value.startswith("sk-xxx"):
                            return value
                    i += 1
                except OSError:
                    break
            winreg.CloseKey(reg)
        except Exception:
            pass
        # 3. Check OPENAI_API_KEY from .env
        if self.openai_api_key and not self.openai_api_key.startswith("sk-xxx"):
            return self.openai_api_key
        return ""

    @property
    def effective_fernet_key(self) -> str:
        """Fernet key source: explicit fernet_key > secret_key."""
        return self.fernet_key or self.secret_key

    # ── Embedding ────────────────────────────────────────────────
    default_embedding_provider: Literal["local", "openai"] = "local"
    embedding_model: str = "all-MiniLM-L6-v2"
    openai_embedding_model: str = "text-embedding-3-small"

    # ── Cross-Encoder Reranker ───────────────────────────────────
    rerank_enabled: bool = True
    rerank_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    rerank_candidate_k: int = 30
    rerank_output_k: int = 5
    rerank_batch_size: int = 16

    # ── Exercise Generation ──────────────────────────────────────────
    exercise_gen_concurrency: int = 5  # Parallel LLM calls for exercise gen

    # ── Quality Gate（入库质量门禁）────────────────────────────────
    # 平台级知识库发布前自动评估，两个指标同时达标才算 verified
    gate_doc_hit_threshold: float = 0.9        # 文档级 top-5 命中率门槛
    gate_context_recall_threshold: float = 0.6  # chunk 级召回率门槛
    gate_k: int = 5                             # 评估 top-k

    @property
    def upload_path(self) -> Path:
        return Path(self.upload_dir)


settings = Settings()
