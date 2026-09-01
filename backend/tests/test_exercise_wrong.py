"""Tests for the "错题本" (wrong-question collection) mode.

Covers:
  - get_due_exercises mode="wrong" returns only ever-wrong exercises
  - get_stats reports wrong_count (total_attempts > total_correct)
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models.base import Base
from app.models.document import Document, DocumentChunk
from app.models.feedback import Exercise, ExerciseState
from app.models.knowledge_base import KBMember, KnowledgeBase
from app.models.user import User
from app.services.exercise_service import ExerciseService


@pytest_asyncio.fixture
async def db():
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


async def _setup(db):
    user = User(id=uuid.uuid4(), username="u1", email="u@t", password_hash="x", role="learner")
    kb = KnowledgeBase(id=uuid.uuid4(), name="kb", owner_id=user.id,
                       kb_type="general", visibility="private", scope="personal")
    db.add_all([user, kb])
    await db.flush()
    doc = Document(id=uuid.uuid4(), kb_id=kb.id, title="d", source_type="markdown",
                   file_size=10, status="indexed")
    db.add(doc)
    await db.flush()
    chunks = [DocumentChunk(id=uuid.uuid4(), doc_id=doc.id, kb_id=kb.id,
                            chunk_index=i, content=f"c{i}", chunk_type="text")
              for i in range(3)]
    db.add_all(chunks)
    await db.flush()
    return user, kb, chunks


def _make_ex(db, kb, chunk, q: str) -> Exercise:
    ex = Exercise(id=uuid.uuid4(), chunk_id=chunk.id, kb_id=kb.id,
                  type="concept_match", question=q,
                  options={"A": "a", "B": "b", "C": "c", "D": "d"}, answer="A",
                  difficulty="easy")
    db.add(ex)
    return ex


def _make_state(db, user, ex, attempts, correct) -> ExerciseState:
    st = ExerciseState(id=uuid.uuid4(), user_id=user.id, exercise_id=ex.id,
                       total_attempts=attempts, total_correct=correct)
    db.add(st)
    return st


@pytest.mark.asyncio
async def test_wrong_mode_returns_only_ever_wrong(db):
    user, kb, chunks = await _setup(db)
    ex_ok = _make_ex(db, kb, chunks[0], "答对的题")
    ex_wrong = _make_ex(db, kb, chunks[1], "答错过的题")
    ex_new = _make_ex(db, kb, chunks[2], "没做过的题")
    _make_state(db, user, ex_ok, attempts=2, correct=2)      # 全对 → 不算错题
    _make_state(db, user, ex_wrong, attempts=2, correct=1)   # 答错过 → 错题
    await db.flush()

    wrong_exs = await ExerciseService.get_due_exercises(
        db, user, str(kb.id), limit=10, mode="wrong")
    ids = {e["id"] for e in wrong_exs}
    assert str(ex_wrong.id) in ids
    assert str(ex_ok.id) not in ids
    assert str(ex_new.id) not in ids


@pytest.mark.asyncio
async def test_stats_wrong_count(db):
    user, kb, chunks = await _setup(db)
    ex_ok = _make_ex(db, kb, chunks[0], "答对的题")
    ex_wrong = _make_ex(db, kb, chunks[1], "答错过的题")
    ex_new = _make_ex(db, kb, chunks[2], "没做过的题")
    _make_state(db, user, ex_ok, attempts=3, correct=3)
    _make_state(db, user, ex_wrong, attempts=3, correct=2)
    await db.flush()

    stats = await ExerciseService.get_stats(db, user, str(kb.id))
    assert stats["wrong_count"] == 1
    assert stats["attempted"] == 2
    assert stats["total_exercises"] == 3
