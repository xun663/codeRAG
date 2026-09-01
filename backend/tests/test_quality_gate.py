"""Tests for the knowledge-base quality gate + scope model.

Covers:
  - QualityGateService: no-QA-data / verified / unverified verdicts,
    chunk-GT optionality, cross-dataset dedup (newest wins)
  - Scope enforcement: platform (admin-only) vs personal (any user)
  - KB visibility: public platform KBs visible to all logged-in users
  - Admin read-only governance over every KB
  - build_quality_report aggregation (cleaning + chunk stats + gate)
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.evaluation.gate import QualityGateService
from app.exceptions import ForbiddenException, NotFoundException
from app.models.base import Base
from app.models.document import Document, DocumentChunk
from app.models.feedback import EvalDataset, EvalQAPair
from app.models.knowledge_base import KBMember, KnowledgeBase
from app.models.user import User
from app.schemas.knowledge_base import KBUpdate
from app.services.kb_service import KBService


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
async def users(db):
    admin = User(id=uuid.uuid4(), username="admin1", email="a@t.com",
                 password_hash="x", role="admin")
    learner = User(id=uuid.uuid4(), username="learner1", email="l@t.com",
                   password_hash="x", role="learner")
    other = User(id=uuid.uuid4(), username="learner2", email="l2@t.com",
                 password_hash="x", role="learner")
    db.add_all([admin, learner, other])
    await db.flush()
    return {"admin": admin, "learner": learner, "other": other}


class FakePipeline:
    """Injected retrieval pipeline: returns canned search results per question."""

    def __init__(self, results_by_question: dict[str, list[dict]]):
        self._results = results_by_question

    async def search_only(self, query, kb_id=None, k=5, strategy="hybrid", rerank=True):
        return {"results": self._results.get(query, [])}


def make_search_result(chunk_id: str, doc_id: str) -> dict:
    return {"chunk_id": chunk_id, "metadata": {"doc_id": doc_id}, "score": 0.9}


def make_kb(db, user: User, name: str, scope: str = "personal",
            visibility: str | None = None) -> KnowledgeBase:
    # 新可见性语义：platform 默认 public（全员可见）；personal 强制私有（分享靠成员）
    if scope == "platform":
        effective = visibility or "public"
    else:
        effective = "private"
    kb = KnowledgeBase(
        id=uuid.uuid4(), name=name, owner_id=user.id,
        kb_type="general", visibility=effective, scope=scope,
    )
    db.add(kb)
    db.add(KBMember(id=uuid.uuid4(), kb_id=kb.id, user_id=user.id, permission="admin"))
    return kb


async def make_dataset(db, user: User, kb: KnowledgeBase, pairs: list[dict],
                       name: str = "ds") -> EvalDataset:
    ds = EvalDataset(id=uuid.uuid4(), name=name, kb_id=kb.id, created_by=user.id)
    db.add(ds)
    await db.flush()
    for p in pairs:
        db.add(EvalQAPair(
            id=uuid.uuid4(), dataset_id=ds.id, question=p["question"],
            relevant_doc_ids=p.get("doc_ids", []),
            ground_truth_chunk_ids=p.get("chunk_ids"),
            ground_truth_chunk_id_type="vector_id",
        ))
    await db.flush()
    return ds


# ═════════════════════════════════════════════════════════════════════
#  Quality gate verdicts
# ═════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_gate_no_qa_data_sets_status(db, users):
    kb = make_kb(db, users["admin"], "empty kb", scope="platform")
    await db.flush()

    report = await QualityGateService.run_gate(db, str(kb.id), pipeline=FakePipeline({}))
    assert report["status"] == QualityGateService.STATUS_NO_QA_DATA
    assert report["total_qa"] == 0
    # persisted
    await db.refresh(kb)
    assert kb.quality_status == QualityGateService.STATUS_NO_QA_DATA
    assert kb.quality_metrics_json["status"] == QualityGateService.STATUS_NO_QA_DATA


@pytest.mark.asyncio
async def test_gate_verified_when_doc_and_chunk_hit(db, users):
    kb = make_kb(db, users["admin"], "py kb", scope="platform")
    await db.flush()
    doc_id = str(uuid.uuid4())
    chunk_id = str(uuid.uuid4())
    await make_dataset(db, users["admin"], kb, [
        {"question": "什么是lambda?", "doc_ids": [doc_id], "chunk_ids": [chunk_id]},
    ])
    pipeline = FakePipeline({
        "什么是lambda?": [make_search_result(chunk_id, doc_id) for _ in range(5)],
    })

    report = await QualityGateService.run_gate(db, str(kb.id), pipeline=pipeline)
    assert report["status"] == QualityGateService.STATUS_VERIFIED
    assert report["metrics"]["avg_doc_hit_at_5"] == 1.0
    assert report["metrics"]["avg_chunk_recall_at_5"] == 1.0
    assert report["doc_level_pairs"] == 1


@pytest.mark.asyncio
async def test_gate_unverified_on_doc_miss(db, users):
    kb = make_kb(db, users["admin"], "kb", scope="platform")
    await db.flush()
    expected_doc = str(uuid.uuid4())
    wrong_doc = str(uuid.uuid4())
    await make_dataset(db, users["admin"], kb, [
        {"question": "q1", "doc_ids": [expected_doc], "chunk_ids": []},
    ])
    pipeline = FakePipeline({
        "q1": [make_search_result(str(uuid.uuid4()), wrong_doc) for _ in range(5)],
    })

    report = await QualityGateService.run_gate(db, str(kb.id), pipeline=pipeline)
    assert report["status"] == QualityGateService.STATUS_UNVERIFIED
    assert report["metrics"]["avg_doc_hit_at_5"] == 0.0


@pytest.mark.asyncio
async def test_gate_unverified_on_chunk_miss(db, users):
    kb = make_kb(db, users["admin"], "kb", scope="platform")
    await db.flush()
    doc_id = str(uuid.uuid4())
    await make_dataset(db, users["admin"], kb, [
        {"question": "q1", "doc_ids": [doc_id], "chunk_ids": [str(uuid.uuid4())]},
    ])
    # correct doc, wrong chunk
    pipeline = FakePipeline({
        "q1": [make_search_result(str(uuid.uuid4()), doc_id) for _ in range(5)],
    })

    report = await QualityGateService.run_gate(db, str(kb.id), pipeline=pipeline)
    assert report["status"] == QualityGateService.STATUS_UNVERIFIED
    assert report["metrics"]["avg_doc_hit_at_5"] == 1.0
    assert report["metrics"]["avg_chunk_recall_at_5"] == 0.0


@pytest.mark.asyncio
async def test_gate_chunk_metric_optional(db, users):
    """Pairs without chunk-level GT must not block the verdict."""
    kb = make_kb(db, users["admin"], "kb", scope="platform")
    await db.flush()
    doc_id = str(uuid.uuid4())
    await make_dataset(db, users["admin"], kb, [
        {"question": "q1", "doc_ids": [doc_id], "chunk_ids": []},
    ])
    pipeline = FakePipeline({
        "q1": [make_search_result(str(uuid.uuid4()), doc_id) for _ in range(5)],
    })

    report = await QualityGateService.run_gate(db, str(kb.id), pipeline=pipeline)
    assert report["status"] == QualityGateService.STATUS_VERIFIED
    assert report["metrics"]["avg_chunk_recall_at_5"] is None
    assert report["chunk_level_pairs"] == 0


@pytest.mark.asyncio
async def test_gate_dedup_prefers_newest_dataset(db, users):
    """Same question in two dataset versions: the newest annotation wins."""
    kb = make_kb(db, users["admin"], "kb", scope="platform")
    await db.flush()
    old_doc = str(uuid.uuid4())   # stale annotation
    new_doc = str(uuid.uuid4())   # corrected annotation

    await make_dataset(db, users["admin"], kb, [
        {"question": "q1", "doc_ids": [old_doc], "chunk_ids": []},
    ], name="问答集")
    await make_dataset(db, users["admin"], kb, [
        {"question": "q1", "doc_ids": [new_doc], "chunk_ids": []},
    ], name="问答集 v2")

    pipeline = FakePipeline({
        "q1": [make_search_result(str(uuid.uuid4()), new_doc) for _ in range(5)],
    })
    report = await QualityGateService.run_gate(db, str(kb.id), pipeline=pipeline)
    assert report["total_qa"] == 1          # deduplicated
    assert report["doc_level_pairs"] == 1
    assert report["metrics"]["avg_doc_hit_at_5"] == 1.0  # uses the NEW annotation


# ═════════════════════════════════════════════════════════════════════
#  Scope model: platform (admin-only) vs personal
# ═════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_create_platform_kb_requires_admin(db, users):
    with pytest.raises(ForbiddenException):
        await KBService.create_kb(db, users["learner"],
                                  type("D", (), {"name": "x", "description": None,
                                                 "kb_type": "general", "visibility": "private",
                                                 "scope": "platform"})())


@pytest.mark.asyncio
async def test_create_kb_default_scope_by_role(db, users):
    kb_admin = await KBService.create_kb(db, users["admin"], type("D", (), {
        "name": "platform kb", "description": None, "kb_type": "general",
        "visibility": "private", "scope": None})())
    assert kb_admin.scope == "platform"

    kb_learner = await KBService.create_kb(db, users["learner"], type("D", (), {
        "name": "personal kb", "description": None, "kb_type": "general",
        "visibility": "private", "scope": None})())
    assert kb_learner.scope == "personal"


@pytest.mark.asyncio
async def test_platform_kb_visible_to_all(db, users):
    """platform 库 public 全员可见 / private 仅 admin（调试）；personal 库始终私有（仅 owner/成员）。"""
    platform_pub = make_kb(db, users["admin"], "curated", scope="platform", visibility="public")
    platform_priv = make_kb(db, users["admin"], "debug curated", scope="platform", visibility="private")
    personal = make_kb(db, users["other"], "personal", scope="personal")
    await db.flush()

    # 普通用户：public platform 可见；private platform（调试中）/ 他人 personal 不可见
    kbs, total = await KBService.list_kbs(db, users["learner"], 1, 50)
    names = [k.name for k in kbs]
    assert "curated" in names            # public platform → visible
    assert "debug curated" not in names  # private platform（调试中）→ 普通用户不可见
    assert "personal" not in names       # other user's personal（始终私有）→ not visible

    # admin：能看到调试中的 private platform 库（治理/调试后切回）
    kbs_admin, _ = await KBService.list_kbs(db, users["admin"], 1, 50)
    assert "debug curated" in [k.name for k in kbs_admin]


@pytest.mark.asyncio
async def test_personal_kb_always_private(db, users):
    """个人库强制私有：显式传 public / 尝试 update 成 public 都会被强制回 private。"""
    # create 时显式传 public → 仍为 private
    personal = make_kb(db, users["other"], "p", scope="personal", visibility="public")
    await db.flush()
    await db.refresh(personal)
    assert personal.visibility == "private"

    # update 尝试改 public → 仍为 private
    await KBService.update_kb(db, personal.id, users["other"], KBUpdate(name="p2", visibility="public"))
    await db.refresh(personal)
    assert personal.visibility == "private"


@pytest.mark.asyncio
async def test_admin_read_governance_over_any_kb(db, users):
    personal = make_kb(db, users["other"], "someone's kb", scope="personal")
    await db.flush()

    # system admin can read any KB (governance)
    fetched = await KBService.get_kb(db, personal.id, users["admin"])
    assert fetched.id == personal.id

    # other learners cannot
    with pytest.raises(ForbiddenException):
        await KBService.get_kb(db, personal.id, users["learner"])

    # admin has NO write bypass
    with pytest.raises(ForbiddenException):
        await KBService.check_kb_write_access(db, personal.id, users["admin"])


# ═════════════════════════════════════════════════════════════════════
#  Quality report aggregation
# ═════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_quality_report_aggregation(db, users):
    kb = make_kb(db, users["admin"], "agg kb", scope="platform")
    await db.flush()
    doc = Document(id=uuid.uuid4(), kb_id=kb.id, title="doc.md", source_type="markdown",
                   metadata_json={"cleaning": {"enabled": True, "before_chars": 1000,
                                               "after_chars": 800, "removed_chars": 200,
                                               "removed_pct": 20.0}})
    db.add(doc)
    db.add(DocumentChunk(id=uuid.uuid4(), doc_id=doc.id, kb_id=kb.id, chunk_index=0,
                         content="a" * 100, token_count=50, chunk_type="text"))
    db.add(DocumentChunk(id=uuid.uuid4(), doc_id=doc.id, kb_id=kb.id, chunk_index=1,
                         content="b" * 100, token_count=150, chunk_type="code_block_python"))
    await db.flush()

    # run a gate so the report carries a verdict
    doc_id = str(doc.id)
    await make_dataset(db, users["admin"], kb, [
        {"question": "q1", "doc_ids": [doc_id], "chunk_ids": []},
    ])
    pipeline = FakePipeline({"q1": [make_search_result(str(uuid.uuid4()), doc_id) for _ in range(5)]})
    await QualityGateService.run_gate(db, str(kb.id), pipeline=pipeline)

    report = await KBService.build_quality_report(db)
    item = next(r for r in report if r["kb_id"] == kb.id)
    assert item["scope"] == "platform"
    assert item["quality_status"] == QualityGateService.STATUS_VERIFIED
    assert item["cleaning"]["removed_pct"] == 20.0
    assert item["cleaning"]["docs_with_cleaning"] == 1
    assert item["chunk_stats"]["total_tokens"] == 200
    assert item["chunk_stats"]["avg_tokens_per_chunk"] == 100.0
    assert item["chunk_stats"]["chunk_type_distribution"] == {"text": 1, "code_block_python": 1}
    assert item["gate"]["metrics"]["avg_doc_hit_at_5"] == 1.0
    assert "per_pair" not in item["gate"]  # per-pair details stripped from report


@pytest.mark.asyncio
async def test_get_kb_404_for_missing(db, users):
    with pytest.raises(NotFoundException):
        await KBService.get_kb(db, uuid.uuid4(), users["admin"])
