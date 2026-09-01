"""Chat and message schemas."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ConversationCreate(BaseModel):
    kb_id: UUID | None = None
    title: str | None = None


class ConversationResponse(BaseModel):
    id: UUID
    user_id: UUID
    kb_id: UUID | None
    title: str | None
    message_count: int
    is_archived: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MessageSend(BaseModel):
    content: str = Field(min_length=1)
    kb_id: UUID | None = None


class RetrievedChunkInfo(BaseModel):
    chunk_id: str
    score: float
    doc_title: str | None = None
    content_preview: str | None = None
    chunk_type: str | None = None


class MessageResponse(BaseModel):
    id: UUID
    conversation_id: UUID
    role: str
    content: str
    content_type: str
    retrieved_chunks: list[dict] | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    latency_ms: int | None = None
    user_rating: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatStreamChunk(BaseModel):
    type: str  # "token", "sources", "done", "error"
    content: str | None = None
    sources: list[dict] | None = None
    conversation_id: UUID | None = None
    message_id: UUID | None = None
