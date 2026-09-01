"""LLM profile management service.

Profiles are admin-configured LLM connection presets (base_url/model plus an
API key stored Fernet-encrypted). At most one profile is active at a time; the
active profile is pushed into the runtime config cache so all LLM calls
immediately use it.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import NotFoundException
from app.llm.crypto import decrypt, encrypt
from app.llm.runtime_config import clear_runtime_config, set_runtime_config
from app.models.feedback import LLMProfile


def _mask(profile: LLMProfile) -> dict:
    """Serialize a profile without exposing any key material."""
    return {
        "id": str(profile.id),
        "name": profile.name,
        "provider": profile.provider,
        "base_url": profile.base_url,
        "model": profile.model,
        "has_key": bool(profile.api_key_encrypted),
        "is_active": profile.is_active,
    }


class LLMProfileService:
    @staticmethod
    async def list_profiles(db: AsyncSession) -> list[dict]:
        result = await db.execute(select(LLMProfile).order_by(LLMProfile.created_at))
        return [_mask(p) for p in result.scalars().all()]

    @staticmethod
    async def create_profile(db: AsyncSession, data, user) -> dict:
        # 首个配置单自动成为激活项
        first = await db.execute(select(LLMProfile).limit(1))
        is_first = first.first() is None
        profile = LLMProfile(
            id=uuid.uuid4(),
            name=data.name or data.model,
            provider="openai",
            base_url=data.base_url,
            model=data.model,
            api_key_encrypted=encrypt(data.api_key or ""),
            is_active=is_first,
        )
        db.add(profile)
        await db.flush()
        if is_first:
            await LLMProfileService._refresh_runtime(profile)
        return _mask(profile)

    @staticmethod
    async def update_profile(db: AsyncSession, profile_id, data, user) -> dict:
        profile = await LLMProfileService._get(db, profile_id)
        if data.name:
            profile.name = data.name
        if data.base_url:
            profile.base_url = data.base_url
        if data.model:
            profile.model = data.model
        if data.api_key:  # 留空保留旧密钥
            profile.api_key_encrypted = encrypt(data.api_key)
        await db.flush()
        if profile.is_active:
            await LLMProfileService._refresh_runtime(profile)
        return _mask(profile)

    @staticmethod
    async def delete_profile(db: AsyncSession, profile_id) -> None:
        profile = await LLMProfileService._get(db, profile_id)
        was_active = profile.is_active
        await db.delete(profile)
        await db.flush()
        if was_active:
            # 删掉激活项：激活剩余第一个，否则清空运行时缓存回退 .env
            next_p = await db.execute(select(LLMProfile).order_by(LLMProfile.created_at).limit(1))
            next_profile = next_p.scalar_one_or_none()
            if next_profile:
                await LLMProfileService.activate_profile(db, next_profile.id)
            else:
                clear_runtime_config()

    @staticmethod
    async def activate_profile(db: AsyncSession, profile_id) -> dict:
        profile = await LLMProfileService._get(db, profile_id)
        await db.execute(update(LLMProfile).where(LLMProfile.id != profile.id).values(is_active=False))
        profile.is_active = True
        await db.flush()
        await LLMProfileService._refresh_runtime(profile)
        return _mask(profile)

    @staticmethod
    async def get_active_profile(db: AsyncSession) -> dict | None:
        result = await db.execute(select(LLMProfile).where(LLMProfile.is_active.is_(True)))
        profile = result.scalar_one_or_none()
        if not profile:
            return None
        return {
            "provider": profile.provider,
            "base_url": profile.base_url,
            "model": profile.model,
            "api_key": decrypt(profile.api_key_encrypted),
        }

    @staticmethod
    async def _get(db: AsyncSession, profile_id) -> LLMProfile:
        uid = uuid.UUID(str(profile_id)) if not isinstance(profile_id, uuid.UUID) else profile_id
        result = await db.execute(select(LLMProfile).where(LLMProfile.id == uid))
        profile = result.scalar_one_or_none()
        if not profile:
            raise NotFoundException("LLM profile not found")
        return profile

    @staticmethod
    async def _refresh_runtime(profile: LLMProfile) -> None:
        """Push the active profile into the process-level runtime cache."""
        set_runtime_config({
            "provider": profile.provider,
            "base_url": profile.base_url,
            "model": profile.model,
            "api_key": decrypt(profile.api_key_encrypted),
        })
