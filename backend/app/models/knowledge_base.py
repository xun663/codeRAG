"""Knowledge Base models."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy import JSON
from app.models.base import CustomUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"

    id: Mapped[uuid.UUID] = mapped_column(CustomUUID, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[uuid.UUID] = mapped_column(CustomUUID, ForeignKey("users.id"), nullable=False)
    kb_type: Mapped[str] = mapped_column(String(20), default="general")
    visibility: Mapped[str] = mapped_column(String(20), default="private")
    # 双层模型: platform（平台策展库，仅 admin 可建，质量门禁） / personal（个人库，隔离）
    scope: Mapped[str] = mapped_column(String(20), default="personal")
    # 质量门禁状态: not_checked / verified / unverified / no_qa_data
    quality_status: Mapped[str] = mapped_column(String(20), default="not_checked")
    # 最近一次门禁评估的完整指标（QualityGateService 写入）
    quality_metrics_json: Mapped[dict | None] = mapped_column(JSON)
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    doc_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    vector_db_name: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="active")
    config_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    # Relationships
    owner = relationship("User", back_populates="knowledge_bases")
    documents = relationship("Document", back_populates="knowledge_base", cascade="all, delete-orphan")
    members = relationship("KBMember", back_populates="knowledge_base", cascade="all, delete-orphan")
    conversations = relationship("Conversation", back_populates="knowledge_base")


class KBMember(Base):
    __tablename__ = "kb_members"

    id: Mapped[uuid.UUID] = mapped_column(CustomUUID, primary_key=True, default=uuid.uuid4)
    kb_id: Mapped[uuid.UUID] = mapped_column(CustomUUID, ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(CustomUUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    permission: Mapped[str] = mapped_column(String(20), default="read")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    __table_args__ = (
        UniqueConstraint("kb_id", "user_id"),
    )

    knowledge_base = relationship("KnowledgeBase", back_populates="members")
    user = relationship("User")
