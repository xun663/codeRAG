"""System configuration endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.middleware.auth import get_current_admin_user
from app.models.user import User
from app.schemas.misc import ConfigUpdate

router = APIRouter(prefix="/config", tags=["config"])


@router.get("")
async def list_config(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_admin_user),
):
    from app.core.monitoring.config_manager import ConfigManager
    return await ConfigManager.list_config(db)


@router.get("/embedding")
async def get_embedding_config(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_admin_user),
):
    from app.core.monitoring.config_manager import ConfigManager
    return await ConfigManager.get_embedding_config(db)


@router.put("/embedding")
async def update_embedding_config(
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    from app.core.monitoring.config_manager import ConfigManager
    return await ConfigManager.update_embedding_config(db, data, current_user)


@router.get("/{key}")
async def get_config(
    key: str,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_admin_user),
):
    from app.core.monitoring.config_manager import ConfigManager
    return await ConfigManager.get_config(db, key)


@router.put("/{key}")
async def update_config(
    key: str,
    data: ConfigUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    from app.core.monitoring.config_manager import ConfigManager
    return await ConfigManager.update_config(db, key, data.config_value, current_user)


@router.post("/test-llm")
async def test_llm(
    config: dict,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_admin_user),
):
    from app.core.monitoring.config_manager import ConfigManager
    return await ConfigManager.test_llm(config)
