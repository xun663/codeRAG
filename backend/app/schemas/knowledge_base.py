"""Knowledge Base schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class KBCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    kb_type: str = "general"
    visibility: str = "private"
    # platform 仅 admin 可建；普通用户请求 platform 会被拒绝并降级为 personal
    scope: Literal["platform", "personal"] | None = None


class KBUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    visibility: str | None = None
    config_json: dict | None = None


class KBMemberAdd(BaseModel):
    user_id: UUID
    permission: str = "read"


class KBMemberResponse(BaseModel):
    id: UUID
    user_id: UUID
    username: str | None = None
    permission: str
    created_at: datetime

    model_config = {"from_attributes": True}


class KBResponse(BaseModel):
    id: UUID
    name: str
    description: str | None
    owner_id: UUID
    kb_type: str
    visibility: str
    scope: str = "personal"
    quality_status: str = "not_checked"
    quality_metrics_json: dict | None = None
    current_version: int
    doc_count: int
    chunk_count: int
    status: str
    config_json: dict
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class KBStatsResponse(BaseModel):
    kb_id: UUID
    doc_count: int
    chunk_count: int
    total_tokens: int
    avg_chunk_size: float


class QualityGateResponse(BaseModel):
    """一次入库质量门禁评估的结果。"""

    kb_id: UUID
    status: str                      # verified / unverified / no_qa_data
    total_qa: int                    # 该 KB 评估数据集中的 QA 总数
    doc_level_pairs: int             # 有文档级 GT 的 QA 数（用于 doc_hit）
    chunk_level_pairs: int           # 有 chunk 级 GT 的 QA 数（用于 context_recall）
    metrics: dict                    # avg_doc_hit_at_5 / avg_doc_mrr / avg_ndcg_at_5 / avg_chunk_recall_at_5
    thresholds: dict                 # 本次使用的门槛值
    latency_ms: int
    run_at: str
    per_pair: list[dict] = Field(default_factory=list)  # 逐条 QA 明细


class QualityCheckTaskResponse(BaseModel):
    """自动化质量门禁任务提交响应（异步，返回 task_id 轮询）。"""

    kb_id: UUID
    task_id: str
    status: str = "pending"


class AutoQualityCheckResponse(BaseModel):
    """自动化质量门禁（用户库自动体检）的结果。"""

    kb_id: UUID
    status: str                      # PASS / WARN / FAIL / no_data
    quality_score: float | None = None
    total_qa: int = 0
    rounds: int = 0
    avg_metrics: dict = Field(default_factory=dict)     # doc_hit/context_recall/mrr/ndcg 均值
    std_metrics: dict = Field(default_factory=dict)     # 同上标准差
    per_round: list[dict] = Field(default_factory=list) # 逐轮汇总
    thresholds: dict = Field(default_factory=dict)
    suggestions: list[str] = Field(default_factory=list)
    eval_meta: dict = Field(default_factory=dict)       # evaluation_id/dataset_id/模型/参数/时间戳
    per_pair: list[dict] = Field(default_factory=list)  # 逐条 QA 明细
    latency_ms: int = 0


class KBQualityReportItem(BaseModel):
    """admin 知识库质量报告中的一行。"""

    kb_id: UUID
    name: str
    scope: str
    visibility: str
    quality_status: str
    current_version: int
    doc_count: int
    chunk_count: int
    cleaning: dict                   # 清洗统计聚合
    chunk_stats: dict                # token/chunk 类型分布
    gate: dict | None                # 最近一次门禁指标
    updated_at: datetime
