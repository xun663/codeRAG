"""Tests for the automated quality gate (AutoQualityGate).

Covers:
  - Metric computation (doc_hit / context_recall / mrr / ndcg) via FakePipeline
  - PASS / WARN / FAIL verdicts + hard-threshold FAIL
  - Small-KB degradation (fewer docs than rounds)
  - Evaluation data persistence (EvalDataset + EvalQAPair with source-trace)
"""

from __future__ import annotations

import hashlib
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.evaluation.auto_gate import AutoQualityGate
from app.models.base import Base
from app.models.document import Document, DocumentChunk
from app.models.feedback import EvalDataset, EvalQAPair
from app.models.knowledge_base import KBMember, KnowledgeBase
from app.models.user import User


# ═════════════════════════════════════════════════════════════════════
#  Fixtures
# ═════════════════════════════════════════════════════════════════════

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


@pytest_asyncio.fixture
async def admin(db) -> User:
    u = User(id=uuid.uuid4(), username="admin1", email="a@t.com",
             password_hash="x", role="admin")
    db.add(u)
    await db.flush()
    return u


def make_kb(db, user: User, name: str = "kb", scope: str = "platform") -> KnowledgeBase:
    kb = KnowledgeBase(id=uuid.uuid4(), name=name, owner_id=user.id,
                       kb_type="general",
                       visibility="public" if scope == "platform" else "private",
                       scope=scope)
    db.add(kb)
    db.add(KBMember(id=uuid.uuid4(), kb_id=kb.id, user_id=user.id, permission="admin"))
    return kb


async def make_doc(db, kb: KnowledgeBase, title: str, n_chunks: int = 2) -> Document:
    d = Document(id=uuid.uuid4(), kb_id=kb.id, title=title, source_type="markdown",
                 file_size=100, status="indexed",
                 doc_hash=hashlib.sha256(title.encode()).hexdigest())
    db.add(d)
    await db.flush()
    for i in range(n_chunks):
        db.add(DocumentChunk(
            id=uuid.uuid4(), doc_id=d.id, kb_id=kb.id, chunk_index=i,
            content=f"chunk {title} #{i}: tuple is an immutable sequence in Python.",
            chunk_type="text",
        ))
    await db.flush()
    return d


class FakeEvalPipeline:
    """Injected retrieval pipeline: returns canned results per question."""

    def __init__(self, results_by_question: dict[str, list[dict]]):
        self._results = results_by_question

    async def search_for_eval(self, query, kb_id=None, k=5, alpha=0.6):
        return {"results": self._results.get(query, [])}


async def chunks_of(db, doc: Document) -> list[DocumentChunk]:
    return (await db.execute(
        select(DocumentChunk).where(DocumentChunk.doc_id == doc.id)
        .order_by(DocumentChunk.chunk_index)
    )).scalars().all()


def hit_result(chunk_id: str, doc_id: str) -> dict:
    return {"chunk_id": str(chunk_id), "metadata": {"doc_id": str(doc_id)}, "score": 0.9}


def miss_result() -> dict:
    return {"chunk_id": str(uuid.uuid4()), "metadata": {"doc_id": str(uuid.uuid4())}, "score": 0.1}


# ═════════════════════════════════════════════════════════════════════
#  Helpers — monkeypatch AutoQuestionGenerator to deterministic output
# ═════════════════════════════════════════════════════════════════════

def _fake_generate(questions: list[dict]):
    async def _gen(chunk_content, doc_title="", count=2):
        return [q for q in questions[:count]]
    return _gen


# ═════════════════════════════════════════════════════════════════════
#  Tests
# ═════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_run_check_pass_when_all_hit(db, admin, monkeypatch):
    from app.core.evaluation import auto_gate as ag
    kb = make_kb(db, admin)
    await db.flush()
    doc = await make_doc(db, kb, "tuple doc", n_chunks=2)
    await db.flush()

    chunks = await chunks_of(db, doc)
    # 问题 = chunk 内容（每个 chunk 的问题唯一），FakePipeline 按 chunk 内容精确命中
    async def _gen(chunk_content, doc_title="", count=2):
        return [{"question": chunk_content, "type": "concept", "difficulty": "medium"}] * max(1, count)
    monkeypatch.setattr(ag.AutoQuestionGenerator, "generate", _gen)
    pipeline = FakeEvalPipeline({
        chunks[0].content: [hit_result(chunks[0].id, doc.id)],
        chunks[1].content: [hit_result(chunks[1].id, doc.id)],
    })

    report = await AutoQualityGate.run_check(
        db, str(kb.id), rounds=1, chunks_per_doc=2, questions_per_chunk=2, pipeline=pipeline)

    assert report["status"] == "PASS"
    assert report["quality_score"] == pytest.approx(1.0)
    assert report["avg_metrics"]["doc_hit"] == 1.0
    assert report["avg_metrics"]["context_recall"] == 1.0
    assert report["total_qa"] == 4  # 2 chunks × 2 questions


@pytest.mark.asyncio
async def test_run_check_hard_fail_on_doc_miss(db, admin, monkeypatch):
    from app.core.evaluation import auto_gate as ag
    kb = make_kb(db, admin)
    await db.flush()
    await make_doc(db, kb, "doc", n_chunks=1)
    await db.flush()

    q = "这个知识库完全没有的问题？"
    monkeypatch.setattr(ag.AutoQuestionGenerator, "generate", _fake_generate([
        {"question": q, "type": "concept", "difficulty": "easy"},
    ]))
    pipeline = FakeEvalPipeline({q: [miss_result()]})  # 检索到错误文档

    report = await AutoQualityGate.run_check(
        db, str(kb.id), rounds=1, chunks_per_doc=1, questions_per_chunk=1, pipeline=pipeline)

    assert report["status"] == "FAIL"
    assert report["avg_metrics"]["doc_hit"] == 0.0
    # 硬门槛触发 FAIL（即使有 suggestions）
    assert any("Doc Hit" in s for s in report["suggestions"])


@pytest.mark.asyncio
async def test_small_kb_degradation(db, admin, monkeypatch):
    """知识库文档数 < rounds → 自动降量为实际文档数，不报错。"""
    from app.core.evaluation import auto_gate as ag
    kb = make_kb(db, admin)
    await db.flush()
    doc = await make_doc(db, kb, "only doc", n_chunks=1)
    await db.flush()

    chunks = await chunks_of(db, doc)
    q = "唯一文档的问题？"
    monkeypatch.setattr(ag.AutoQuestionGenerator, "generate", _fake_generate([
        {"question": q, "type": "concept", "difficulty": "easy"},
    ]))
    pipeline = FakeEvalPipeline({q: [hit_result(chunks[0].id, doc.id)]})

    report = await AutoQualityGate.run_check(
        db, str(kb.id), rounds=5, chunks_per_doc=1, questions_per_chunk=1, pipeline=pipeline)

    assert report["rounds"] == 1          # 只有 1 篇文档 → 1 轮
    assert report["total_qa"] == 1
    assert report["status"] in ("PASS", "WARN", "FAIL")
    assert report["per_round"][0]["round"] == 1


@pytest.mark.asyncio
async def test_run_check_persists_dataset_with_source_trace(db, admin, monkeypatch):
    from app.core.evaluation import auto_gate as ag
    kb = make_kb(db, admin)
    await db.flush()
    doc = await make_doc(db, kb, "trace doc", n_chunks=1)
    await db.flush()

    chunks = await chunks_of(db, doc)
    q = "持久化测试问题？"
    monkeypatch.setattr(ag.AutoQuestionGenerator, "generate", _fake_generate([
        {"question": q, "type": "debugging", "difficulty": "hard"},
    ]))
    pipeline = FakeEvalPipeline({q: [hit_result(chunks[0].id, doc.id)]})

    report = await AutoQualityGate.run_check(
        db, str(kb.id), rounds=1, chunks_per_doc=1, questions_per_chunk=1, pipeline=pipeline)

    # 数据集落库
    dss = (await db.execute(select(EvalDataset).where(EvalDataset.kb_id == kb.id))).scalars().all()
    assert len(dss) == 1
    assert dss[0].name.startswith("Auto Quality Check")
    assert str(dss[0].id) == report["eval_meta"]["dataset_id"]

    # QA pair 带溯源字段
    pairs = (await db.execute(select(EvalQAPair).where(EvalQAPair.dataset_id == dss[0].id))).scalars().all()
    assert len(pairs) == 1
    p = pairs[0]
    assert p.source_document_id == str(doc.id)
    assert p.source_chunk_id == str(chunks[0].id)
    assert p.chunk_content_hash  # 非空
    assert p.question_type == "debugging"
    assert p.difficulty == "hard"
    assert p.relevant_doc_ids == [str(doc.id)]
    assert p.ground_truth_chunk_ids == [str(chunks[0].id)]
    assert p.eval_metadata["round"] == 1
