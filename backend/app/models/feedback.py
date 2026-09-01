"""Feedback, evaluation, experiment, learning path, config, and log models."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Integer, SmallInteger, String, Text, UniqueConstraint, func,
)
from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CustomUUID


class FeedbackDetail(Base):
    __tablename__ = "feedback_details"

    id: Mapped[uuid.UUID] = mapped_column(CustomUUID, primary_key=True, default=uuid.uuid4)
    message_id: Mapped[uuid.UUID] = mapped_column(CustomUUID, ForeignKey("messages.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(CustomUUID, ForeignKey("users.id"), nullable=False)
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    feedback_type: Mapped[str | None] = mapped_column(String(20))
    comment: Mapped[str | None] = mapped_column(Text)
    is_helpful: Mapped[bool | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    message = relationship("Message", back_populates="feedback_details")
    user = relationship("User", back_populates="feedbacks")


class EvalDataset(Base):
    __tablename__ = "eval_datasets"

    id: Mapped[uuid.UUID] = mapped_column(CustomUUID, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    kb_id: Mapped[uuid.UUID | None] = mapped_column(CustomUUID, ForeignKey("knowledge_bases.id"))
    created_by: Mapped[uuid.UUID] = mapped_column(CustomUUID, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    qa_pairs = relationship("EvalQAPair", back_populates="dataset", cascade="all, delete-orphan")


class EvalQAPair(Base):
    __tablename__ = "eval_qa_pairs"

    id: Mapped[uuid.UUID] = mapped_column(CustomUUID, primary_key=True, default=uuid.uuid4)
    dataset_id: Mapped[uuid.UUID] = mapped_column(CustomUUID, ForeignKey("eval_datasets.id", ondelete="CASCADE"), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    reference_answer: Mapped[str | None] = mapped_column(Text)

    # ── 精标注字段 ──
    # 文档级 Ground Truth（Phase 2 新增，主指标用）
    relevant_doc_ids: Mapped[list | None] = mapped_column(JSON)
    relevant_doc_titles: Mapped[list | None] = mapped_column(JSON)
    # Chunk 级 Ground Truth（Phase 1）
    ground_truth_chunk_ids: Mapped[list | None] = mapped_column(JSON)
    ground_truth_chunk_id_type: Mapped[str | None] = mapped_column(String(20), default="vector_id")
    # Answer Span（可选，深入分析用）
    answer_span: Mapped[dict | None] = mapped_column(JSON)
    # 标注说明
    ground_truth_notes: Mapped[str | None] = mapped_column(Text)

    # ── 课程/主题标签（支持后续新知识库扩展）──
    subject: Mapped[str | None] = mapped_column(String(50))

    # ── 已有字段 ──
    expected_chunk_ids: Mapped[list | None] = mapped_column(JSON)
    difficulty: Mapped[str | None] = mapped_column(String(10))
    tags: Mapped[list | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    # ── 自动质量门禁溯源字段（Phase 1 新增，全 nullable，人工 GT 不受影响）──
    source_document_id: Mapped[str | None] = mapped_column(String(36))   # 出题来源 doc UUID
    source_document_hash: Mapped[str | None] = mapped_column(String(64)) # Document.doc_hash
    source_chunk_id: Mapped[str | None] = mapped_column(String(36))      # 出题来源 chunk UUID
    chunk_content_hash: Mapped[str | None] = mapped_column(String(64))   # sha256(chunk.content)，跨重索引稳定锚点
    question_type: Mapped[str | None] = mapped_column(String(20))        # concept/comparison/usage/code/debugging/reasoning
    eval_metadata: Mapped[dict | None] = mapped_column(JSON)             # round/难度/检索参数/chunking_version 等
    is_stale: Mapped[bool | None] = mapped_column(Boolean, default=False)  # 重索引后内容已变 → 自动重生成

    dataset = relationship("EvalDataset", back_populates="qa_pairs")
    results = relationship("EvalResult", back_populates="qa_pair", cascade="all, delete-orphan")


class EvalResult(Base):
    __tablename__ = "eval_results"

    id: Mapped[uuid.UUID] = mapped_column(CustomUUID, primary_key=True, default=uuid.uuid4)
    qa_pair_id: Mapped[uuid.UUID] = mapped_column(CustomUUID, ForeignKey("eval_qa_pairs.id", ondelete="CASCADE"), nullable=False)
    experiment_id: Mapped[uuid.UUID | None] = mapped_column(CustomUUID, ForeignKey("experiments.id"))
    recall_at_1: Mapped[float | None] = mapped_column(Float)
    recall_at_3: Mapped[float | None] = mapped_column(Float)
    recall_at_5: Mapped[float | None] = mapped_column(Float)
    mrr: Mapped[float | None] = mapped_column(Float)
    precision_at_k: Mapped[float | None] = mapped_column(Float)

    # ── 新增指标（Phase 1）──
    hit_rate_at_5: Mapped[float | None] = mapped_column(Float)
    # ── 文档级指标（Phase 2）──
    doc_hit_at_5: Mapped[float | None] = mapped_column(Float)
    doc_mrr: Mapped[float | None] = mapped_column(Float)
    ndcg_at_5: Mapped[float | None] = mapped_column(Float)

    faithfulness: Mapped[float | None] = mapped_column(Float)
    pass_at_1: Mapped[float | None] = mapped_column(Float)
    pass_at_k: Mapped[float | None] = mapped_column(Float)
    generated_answer: Mapped[str | None] = mapped_column(Text)
    retrieved_chunk_ids: Mapped[list | None] = mapped_column(JSON)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    qa_pair = relationship("EvalQAPair", back_populates="results")
    experiment = relationship("Experiment", back_populates="results")


class Experiment(Base):
    __tablename__ = "experiments"

    id: Mapped[uuid.UUID] = mapped_column(CustomUUID, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column(CustomUUID, ForeignKey("users.id"), nullable=False)
    dataset_id: Mapped[uuid.UUID] = mapped_column(CustomUUID, ForeignKey("eval_datasets.id"), nullable=False)
    config_a: Mapped[dict] = mapped_column(JSON, nullable=False)
    config_b: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    results_json: Mapped[dict | None] = mapped_column(JSON)
    winner: Mapped[str | None] = mapped_column(String(1))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    results = relationship("EvalResult", back_populates="experiment")


class LearningPath(Base):
    __tablename__ = "learning_paths"

    id: Mapped[uuid.UUID] = mapped_column(CustomUUID, primary_key=True, default=uuid.uuid4)
    kb_id: Mapped[uuid.UUID] = mapped_column(CustomUUID, ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False)
    concept_a: Mapped[str] = mapped_column(String(200), nullable=False)
    concept_b: Mapped[str] = mapped_column(String(200), nullable=False)
    relationship: Mapped[str] = mapped_column(String(30), nullable=False)
    strength: Mapped[float] = mapped_column(Float, default=1.0)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    __table_args__ = (UniqueConstraint("kb_id", "concept_a", "concept_b"),)


class SystemConfig(Base):
    __tablename__ = "system_config"

    id: Mapped[uuid.UUID] = mapped_column(CustomUUID, primary_key=True, default=uuid.uuid4)
    config_key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    config_value: Mapped[dict] = mapped_column(JSON, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(CustomUUID, ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class OperationLog(Base):
    __tablename__ = "operation_logs"

    id: Mapped[uuid.UUID] = mapped_column(CustomUUID, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(CustomUUID, ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(30))
    resource_id: Mapped[uuid.UUID | None] = mapped_column(CustomUUID)
    detail_json: Mapped[dict | None] = mapped_column(JSON)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Exercise(Base):
    """Quiz questions auto-generated from knowledge base chunks.

    Each chunk produces 1-2 exercises during ingestion. Exercises are
    linked to their source chunk for traceability and citation.
    """
    __tablename__ = "exercises"

    id: Mapped[uuid.UUID] = mapped_column(CustomUUID, primary_key=True, default=uuid.uuid4)
    chunk_id: Mapped[uuid.UUID] = mapped_column(CustomUUID, ForeignKey("document_chunks.id", ondelete="CASCADE"), nullable=False)
    kb_id: Mapped[uuid.UUID] = mapped_column(CustomUUID, ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False)
    doc_id: Mapped[uuid.UUID | None] = mapped_column(CustomUUID, ForeignKey("documents.id", ondelete="SET NULL"))
    type: Mapped[str] = mapped_column(String(30), nullable=False)  # concept_match | code_fill | output_predict | error_diagnose
    question: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[dict] = mapped_column(JSON)       # {"A": "...", "B": "...", "C": "...", "D": "..."}
    answer: Mapped[str] = mapped_column(String(1), nullable=False)  # A/B/C/D
    explanation: Mapped[str | None] = mapped_column(Text)
    difficulty: Mapped[str] = mapped_column(String(10), default="medium")  # easy | medium | hard
    priority: Mapped[str] = mapped_column(String(10), default="normal")    # high | normal | low
    topic: Mapped[str | None] = mapped_column(String(100))
    tags: Mapped[list | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    chunk = relationship("DocumentChunk")
    states = relationship("ExerciseState", back_populates="exercise", cascade="all, delete-orphan")


class ExerciseState(Base):
    """Per-user SM-2 spaced repetition state for each exercise.

    One row per (user, exercise) pair. Tracks review intervals,
    ease factor, mastery, and consecutive errors for weak-point detection.
    """
    __tablename__ = "exercise_states"

    id: Mapped[uuid.UUID] = mapped_column(CustomUUID, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(CustomUUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    exercise_id: Mapped[uuid.UUID] = mapped_column(CustomUUID, ForeignKey("exercises.id", ondelete="CASCADE"), nullable=False)
    interval: Mapped[int] = mapped_column(Integer, default=0)       # days until next review
    ease_factor: Mapped[float] = mapped_column(Float, default=2.5)
    repetitions: Mapped[int] = mapped_column(Integer, default=0)
    due_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    last_quality: Mapped[int | None] = mapped_column(Integer)       # 0-5 SM-2 quality
    consecutive_correct: Mapped[int] = mapped_column(Integer, default=0)
    consecutive_wrong: Mapped[int] = mapped_column(Integer, default=0)
    total_attempts: Mapped[int] = mapped_column(Integer, default=0)
    total_correct: Mapped[int] = mapped_column(Integer, default=0)
    is_mastered: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (UniqueConstraint("user_id", "exercise_id"),)

    exercise = relationship("Exercise", back_populates="states")
    user = relationship("User")


class LLMProfile(Base):
    """Admin-configured LLM connection profiles.

    Each profile is one named configuration (provider/base_url/model), with the
    API key stored Fernet-encrypted (never plaintext). At most one profile is
    active at a time; the active profile drives all LLM calls.
    """
    __tablename__ = "llm_profiles"

    id: Mapped[uuid.UUID] = mapped_column(CustomUUID, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)      # 配置单说明，默认=model
    provider: Mapped[str] = mapped_column(String(20), default="openai")
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    api_key_encrypted: Mapped[str] = mapped_column(String(500), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)
