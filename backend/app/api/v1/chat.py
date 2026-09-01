"""Chat and streaming endpoints."""
from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.middleware.auth import get_current_user
from app.models.user import User
from app.schemas.common import PaginatedResponse
from app.schemas.chat import (
    ConversationCreate, ConversationResponse, MessageSend, MessageResponse,
)
from app.services.chat_service import ChatService

router = APIRouter(prefix="/chat", tags=["chat"])


@router.get("/conversations", response_model=PaginatedResponse[ConversationResponse])
async def list_conversations(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    convs, total = await ChatService.list_conversations(db, current_user, page, page_size)
    return PaginatedResponse(
        items=convs, total=total, page=page, page_size=page_size,
        pages=(total + page_size - 1) // page_size,
    )


@router.post("/conversations", response_model=ConversationResponse, status_code=201)
async def create_conversation(
    data: ConversationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await ChatService.create_conversation(db, current_user, data.kb_id, data.title)


@router.get("/conversations/{conv_id}", response_model=ConversationResponse)
async def get_conversation(
    conv_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await ChatService.get_conversation(db, conv_id, current_user)


@router.delete("/conversations/{conv_id}")
async def delete_conversation(
    conv_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await ChatService.delete_conversation(db, conv_id, current_user)
    return {"message": "Conversation deleted"}


@router.get("/conversations/{conv_id}/messages", response_model=PaginatedResponse[MessageResponse])
async def list_messages(
    conv_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    msgs, total = await ChatService.list_messages(db, conv_id, current_user, page, page_size)
    return PaginatedResponse(
        items=msgs, total=total, page=page, page_size=page_size,
        pages=(total + page_size - 1) // page_size,
    )


@router.post("/conversations/{conv_id}/messages", response_model=MessageResponse)
async def send_message(
    conv_id: UUID,
    data: MessageSend,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await ChatService.send_message_and_get_answer(db, conv_id, current_user, data)


@router.post("/conversations/{conv_id}/stream")
async def stream_chat(
    conv_id: UUID,
    data: MessageSend,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """SSE streaming chat endpoint."""
    async def event_stream():
        try:
            async for chunk in ChatService.stream_answer(
                db, conv_id, current_user, data
            ):
                yield f"data: {json.dumps(chunk)}\n\n"
                if chunk.get("type") == "done":
                    break
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
