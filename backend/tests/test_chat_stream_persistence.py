"""Regression test: streaming chat must persist the assistant message.

Root cause (2026-08-25):
In ``ChatService.stream_answer``, the assistant-message insert (``db.add`` +
``flush``) was placed AFTER ``yield {"type": "done", ...}`` in all three
routes (tool / rag / pure_llm). The SSE endpoint (``app/api/v1/chat.py``
``event_stream``) breaks out of the ``async for`` the moment it sees a
``done`` chunk, which closes the ``stream_answer`` generator via ``aclose()``
(GeneratorExit thrown at the yield point). Code after the ``done`` yield
therefore NEVER runs — so the assistant message was silently dropped.

User messages survived because they are flushed at the top of
``stream_answer``, before the first yield. Symptom: after re-login or
switching features, only the user's questions remain; the answers are gone.

Fix: build + ``db.add`` + ``flush`` the assistant message BEFORE yielding the
``done`` chunk, in every route.

These tests reproduce the exact break-on-done consumption pattern from the
endpoint and assert the assistant message is flushed into the session.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.rag.intent_classifier import Intent
from app.models.base import Base
from app.models.conversation import Conversation, Message
from app.models.user import User
from app.schemas.chat import MessageSend
from app.services import chat_service
from app.services.chat_service import ChatService
from tests.conftest import MockLLMProvider


# ═════════════════════════════════════════════════════════════════════
#  Fixtures
# ═════════════════════════════════════════════════════════════════════

@pytest_asyncio.fixture
async def db():
    """In-memory SQLite DB with the full schema."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def user(db) -> User:
    u = User(id=uuid.uuid4(), username="admin1", email="a@t.com",
             password_hash="x", role="admin")
    db.add(u)
    await db.flush()
    return u


@pytest_asyncio.fixture
async def conv(db, user) -> Conversation:
    c = Conversation(id=uuid.uuid4(), user_id=user.id, kb_id=None, title="test")
    db.add(c)
    await db.flush()
    return c


# ═════════════════════════════════════════════════════════════════════
#  Helpers
# ═════════════════════════════════════════════════════════════════════

async def _consume_like_sse(agen):
    """Replicate app/api/v1/chat.py event_stream: break on the first 'done'."""
    chunks = []
    async for chunk in agen:
        chunks.append(chunk)
        if chunk.get("type") == "done":
            break
    return chunks


def _make_classify(intent: Intent):
    async def _fake(*args, **kwargs):
        return intent
    return _fake


async def _assert_assistant_persisted(db, conv, expected_substr: str):
    """Assert both user and assistant messages are flushed into the session."""
    r_user = await db.execute(
        select(Message).where(Message.conversation_id == conv.id, Message.role == "user")
    )
    user_msgs = r_user.scalars().all()
    assert len(user_msgs) == 1, f"user 消息数异常: {len(user_msgs)}"

    r_assist = await db.execute(
        select(Message).where(Message.conversation_id == conv.id, Message.role == "assistant")
    )
    assist_msgs = r_assist.scalars().all()
    assert len(assist_msgs) == 1, (
        f"❌ assistant 消息未入库（复现 bug）: {len(assist_msgs)} 条"
    )
    assert expected_substr in assist_msgs[0].content
    assert conv.message_count == 2, f"message_count 应为 2（user+assistant），实际 {conv.message_count}"


# ═════════════════════════════════════════════════════════════════════
#  Tests — each route must persist the assistant message
# ═════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_stream_pure_llm_persists_assistant(db, user, conv, monkeypatch):
    monkeypatch.setattr(chat_service, "classify_intent", _make_classify(Intent.GREETING))
    monkeypatch.setattr(chat_service, "is_rag_needed", lambda *a: False)
    monkeypatch.setattr(
        "app.llm.factory.get_llm_provider",
        lambda: MockLLMProvider("Mock pure llm answer."),
    )

    chunks = await _consume_like_sse(
        ChatService.stream_answer(db, conv.id, user, MessageSend(content="hello"))
    )
    assert chunks[-1]["type"] == "done"
    await _assert_assistant_persisted(db, conv, "Mock pure llm answer")


@pytest.mark.asyncio
async def test_stream_tool_persists_assistant(db, user, conv, monkeypatch):
    monkeypatch.setattr(chat_service, "classify_intent", _make_classify(Intent.TOOL))
    monkeypatch.setattr(chat_service, "is_rag_needed", lambda *a: False)
    monkeypatch.setattr(
        chat_service, "match_tool",
        lambda q: ("time", lambda q: {"content": "现在是下午 3 点"}),
    )

    chunks = await _consume_like_sse(
        ChatService.stream_answer(db, conv.id, user, MessageSend(content="现在几点了"))
    )
    assert chunks[-1]["type"] == "done"
    await _assert_assistant_persisted(db, conv, "现在是下午 3 点")


@pytest.mark.asyncio
async def test_stream_rag_persists_assistant(db, user, conv, monkeypatch):
    class FakePipeline:
        async def generate_stream(self, **kwargs):
            yield {"type": "phase", "phase": "searching", "message": "检索中"}
            yield {"type": "token", "content": "RAG "}
            yield {"type": "done", "content": "RAG answer",
                   "sources": [{"id": "c1"}], "latency_ms": 5}

    monkeypatch.setattr(chat_service, "classify_intent", _make_classify(Intent.KNOWLEDGE))
    monkeypatch.setattr(chat_service, "is_rag_needed", lambda *a: True)
    monkeypatch.setattr(chat_service, "RAGPipeline", FakePipeline)

    chunks = await _consume_like_sse(
        ChatService.stream_answer(
            db, conv.id, user,
            MessageSend(content="什么是异常", kb_id=uuid.uuid4()),
        )
    )
    assert chunks[-1]["type"] == "done"
    # done chunk 现在应携带 source_meta（原来在 yield 之后设置，同样被跳过）
    assert chunks[-1].get("source_meta", {}).get("source_type") == "knowledge"
    await _assert_assistant_persisted(db, conv, "RAG answer")
