"""Search, feedback, eval, config, and monitoring schemas."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


# ── Search ──────────────────────────────────────────────────
class SearchRequest(BaseModel):
    q: str
    kb_id: UUID | None = None
    k: int = Field(default=5, ge=1, le=100)
    strategy: str = "hybrid"  # dense, sparse, hybrid
    alpha: float = Field(default=0.6, ge=0.0, le=1.0)
    rerank: bool = False


class SearchResult(BaseModel):
    chunk_id: str
    doc_id: UUID | None
    doc_title: str | None
    content_preview: str
    score: float
    chunk_type: str
    metadata: dict


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]
    total_found: int
    latency_ms: int


# ── Feedback ────────────────────────────────────────────────
class MessageRatingCreate(BaseModel):
    rating: int = Field(ge=1, le=5)


class FeedbackDetailCreate(BaseModel):
    rating: int = Field(ge=1, le=5)
    feedback_type: str | None = None
    comment: str | None = None
    is_helpful: bool | None = None


# ── Evaluation ──────────────────────────────────────────────
class EvalDatasetResponse(BaseModel):
    id: UUID
    name: str
    description: str | None = None
    kb_id: UUID | None = None
    created_by: UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class EvalDatasetCreate(BaseModel):
    name: str
    description: str | None = None
    kb_id: UUID | None = None


class EvalQAPairCreate(BaseModel):
    question: str
    reference_answer: str | None = None
    # 文档级 Ground Truth（主指标 doc_hit/MRR/NDCG 用）
    relevant_doc_ids: list[UUID] | None = None
    relevant_doc_titles: list[str] | None = None
    # 精标注 ground truth chunk（替代 expected_chunk_ids）
    ground_truth_chunk_ids: list[str] | None = None
    ground_truth_chunk_id_type: str | None = "vector_id"
    ground_truth_notes: str | None = None
    subject: str | None = None
    # 向后兼容
    expected_chunk_ids: list[UUID] | None = None
    difficulty: str | None = None
    tags: list[str] | None = None


# ── Config ──────────────────────────────────────────────────
class ConfigUpdate(BaseModel):
    config_value: dict


# ── LLM Profiles ────────────────────────────────────────────
class LLMProfileCreate(BaseModel):
    name: str | None = None          # 配置单说明，默认=model
    base_url: str
    model: str
    api_key: str | None = None


class LLMProfileUpdate(BaseModel):
    name: str | None = None
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None       # 留空则保留旧密钥


# ── Monitoring ──────────────────────────────────────────────
class ModelUsage(BaseModel):
    provider: str | None = None
    model: str | None = None
    count: int = 0


class KBStorageItem(BaseModel):
    name: str
    docs: int = 0
    chunks: int = 0
    vectordb_chunks: int = 0


class HealthCheckDetail(BaseModel):
    status: str  # ok / error
    detail: str | None = None


class SystemHealth(BaseModel):
    status: str  # ok / degraded
    checks: dict[str, HealthCheckDetail] = {}


class LatencyStats(BaseModel):
    avg_ms: float = 0
    min_ms: int = 0
    max_ms: int = 0
    total_requests: int = 0


class TokenStats(BaseModel):
    total_prompt: int = 0
    total_completion: int = 0
    avg_per_request: int = 0
    total_requests: int = 0


class RatingSummary(BaseModel):
    avg: float = 0
    total: int = 0
    distribution: dict[int, int] = {}


class DashboardSummary(BaseModel):
    system_health: SystemHealth
    usage: dict[str, int] = {}
    latency: LatencyStats
    tokens: TokenStats
    models: list[ModelUsage] = []
    kb_storage: list[KBStorageItem] = []
    ratings: RatingSummary
    recent_activity: list[dict] = []
