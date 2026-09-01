"""LLM profile endpoints (admin)."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.middleware.auth import get_current_admin_user
from app.models.user import User
from app.schemas.misc import LLMProfileCreate, LLMProfileUpdate
from app.services.llm_profile_service import LLMProfileService

router = APIRouter(prefix="/llm-profiles", tags=["llm_profiles"])


@router.get("")
async def list_profiles(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_admin_user),
):
    return await LLMProfileService.list_profiles(db)


@router.post("", status_code=201)
async def create_profile(
    data: LLMProfileCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    return await LLMProfileService.create_profile(db, data, current_user)


@router.put("/{profile_id}")
async def update_profile(
    profile_id: UUID,
    data: LLMProfileUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    return await LLMProfileService.update_profile(db, profile_id, data, current_user)


@router.delete("/{profile_id}")
async def delete_profile(
    profile_id: UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_admin_user),
):
    await LLMProfileService.delete_profile(db, profile_id)
    return {"message": "Profile deleted"}


@router.post("/{profile_id}/activate")
async def activate_profile(
    profile_id: UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_admin_user),
):
    return await LLMProfileService.activate_profile(db, profile_id)
