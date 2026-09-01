"""Alembic migrations environment — auto-configured for CodeRAG models."""
from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

# Ensure backend/ is on sys.path so `from app.models` works
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Alembic Config object
config = context.config

# Set up loggers
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ── Import all ORM models so autogenerate detects them ──
from app.models.base import Base  # noqa: E402
from app.models import *           # noqa: E402, F403 — registers every model on Base

target_metadata = Base.metadata

# DB 地址单一来源：用应用 settings（.env）覆盖 alembic.ini 里写死的旧 URL
# （alembic.ini 曾硬编码 root@localhost:3309，生产连不上且是本地残留）
from app.config import settings  # noqa: E402
config.set_main_option("sqlalchemy.url", settings.database_url_sync)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (generate SQL script, no DB connection)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (execute directly on DB)."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
