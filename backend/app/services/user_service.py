"""User service."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.jwt import create_access_token, create_refresh_token, decode_token
from app.core.auth.password import hash_password, verify_password
from app.exceptions import ConflictException, NotFoundException, UnauthorizedException
from app.models.knowledge_base import KBMember, KnowledgeBase
from app.models.user import User
from app.schemas.user import UserCreate, UserLogin, UserUpdate, PasswordChange


class UserService:
    @staticmethod
    async def create_user(db: AsyncSession, data: UserCreate) -> User:
        existing = await db.execute(select(User).where(User.username == data.username))
        if existing.scalar_one_or_none():
            raise ConflictException(f"Username '{data.username}' already exists")

        existing_email = await db.execute(select(User).where(User.email == data.email))
        if existing_email.scalar_one_or_none():
            raise ConflictException(f"Email '{data.email}' already exists")

        user = User(
            id=uuid.uuid4(),
            username=data.username,
            email=data.email,
            password_hash=hash_password(data.password),
            display_name=data.display_name,
        )
        db.add(user)
        await db.flush()

        # Auto-create personal KB
        kb = KnowledgeBase(
            id=uuid.uuid4(), name=f"{user.username}'s KB",
            description="Personal knowledge base", owner_id=user.id,
            vector_db_name=f"kb_{uuid.uuid4().hex[:16]}",
        )
        db.add(kb)
        await db.flush()
        db.add(KBMember(id=uuid.uuid4(), kb_id=kb.id, user_id=user.id, permission="admin"))
        await db.flush()
        return user

    @staticmethod
    async def login(db: AsyncSession, data: UserLogin) -> dict:
        result = await db.execute(select(User).where(User.username == data.username))
        user = result.scalar_one_or_none()
        if not user or not verify_password(data.password, user.password_hash):
            raise UnauthorizedException("Invalid username or password")
        if not user.is_active:
            raise UnauthorizedException("Account is disabled")

        access = create_access_token({"sub": str(user.id)})
        refresh = create_refresh_token({"sub": str(user.id)})
        return {"access_token": access, "refresh_token": refresh, "token_type": "bearer"}

    @staticmethod
    def refresh_token(token: str) -> dict:
        payload = decode_token(token)
        if payload.get("type") != "refresh":
            raise UnauthorizedException("Invalid token type")
        user_id = payload.get("sub")
        access = create_access_token({"sub": user_id})
        new_refresh = create_refresh_token({"sub": user_id})
        return {"access_token": access, "refresh_token": new_refresh, "token_type": "bearer"}

    @staticmethod
    async def get_user_by_id(db: AsyncSession, user_id) -> User:
        uid = uuid.UUID(str(user_id)) if not isinstance(user_id, uuid.UUID) else user_id
        result = await db.execute(select(User).where(User.id == uid))
        user = result.scalar_one_or_none()
        if not user:
            raise NotFoundException(f"User '{user_id}' not found")
        return user

    @staticmethod
    async def update_user(db: AsyncSession, user_id, data: UserUpdate) -> User:
        user = await UserService.get_user_by_id(db, user_id)
        for key in ("email", "display_name", "role", "is_active"):
            val = getattr(data, key, None)
            if val is not None:
                setattr(user, key, val)
        await db.flush()
        return user

    @staticmethod
    async def delete_user(db: AsyncSession, user_id) -> None:
        user = await UserService.get_user_by_id(db, user_id)
        user.is_active = False
        await db.flush()

    @staticmethod
    async def change_password(db: AsyncSession, user: User, data: PasswordChange) -> None:
        if not verify_password(data.old_password, user.password_hash):
            raise UnauthorizedException("Current password is incorrect")
        user.password_hash = hash_password(data.new_password)
        await db.flush()

    @staticmethod
    async def list_users(db: AsyncSession, page: int = 1, page_size: int = 20) -> tuple[list[User], int]:
        count_r = await db.execute(select(func.count(User.id)))
        total = count_r.scalar_one()
        offset = (page - 1) * page_size
        result = await db.execute(select(User).order_by(User.created_at.desc()).offset(offset).limit(page_size))
        return list(result.scalars().all()), total

    @staticmethod
    async def search_users(db: AsyncSession, query: str, limit: int = 10) -> list[User]:
        """按用户名模糊搜索（供知识库成员分享——任何登录用户可用）。"""
        q = (query or "").strip()
        if not q:
            return []
        result = await db.execute(
            select(User)
            .where(User.username.like(f"%{q}%"))
            .order_by(User.username)
            .limit(max(1, min(limit, 20)))
        )
        return list(result.scalars().all())
