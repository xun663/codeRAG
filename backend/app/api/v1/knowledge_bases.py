"""Knowledge Base endpoints."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.db.session import get_db
from app.middleware.auth import get_current_admin_user, get_current_user
from app.models.knowledge_base import KBMember
from app.models.user import User
from app.schemas.common import PaginatedResponse
from app.schemas.knowledge_base import (
    KBCreate, KBUpdate, KBMemberAdd, KBMemberResponse,
    KBResponse, KBStatsResponse, QualityGateResponse, KBQualityReportItem,
    QualityCheckTaskResponse,
)
from app.services.kb_service import KBService

router = APIRouter(prefix="/kbs", tags=["knowledge_bases"])


@router.get("", response_model=PaginatedResponse[KBResponse])
async def list_kbs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    kbs, total = await KBService.list_kbs(db, current_user, page, page_size)
    return PaginatedResponse(
        items=kbs, total=total, page=page, page_size=page_size,
        pages=(total + page_size - 1) // page_size,
    )


@router.post("", response_model=KBResponse, status_code=201)
async def create_kb(
    data: KBCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await KBService.create_kb(db, current_user, data)


# NOTE: 必须注册在 GET /{kb_id} 之前，否则 "quality-report" 会被当作 kb_id
@router.get("/quality-report", response_model=list[KBQualityReportItem])
async def quality_report(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_admin_user),
):
    """[admin] 全库质量报告 — 每个知识库的清洗/分块/门禁指标聚合。"""
    return await KBService.build_quality_report(db)


@router.post("/{kb_id}/quality-gate", response_model=QualityGateResponse)
async def run_quality_gate(
    kb_id: UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_admin_user),
):
    """[admin] 对指定知识库运行入库质量门禁（检索级评估，不调 LLM）。"""
    from app.core.evaluation.gate import QualityGateService
    return await QualityGateService.run_gate(db, kb_id)


@router.post("/{kb_id}/quality-check", response_model=QualityCheckTaskResponse)
async def run_auto_quality_check(
    kb_id: UUID,
    _admin: User = Depends(get_current_admin_user),
):
    """[admin] 自动化质量门禁（异步）——随机采样文档/Chunk 自动出题+自动 GT，
    跑真实检索链路。提交后返回 task_id，用 GET /kbs/quality-check/tasks/{id} 轮询。

    同步跑需数分钟，会阻塞单 worker 下的其他请求，故走 Celery 后台任务。
    评估数据落库（EvalDataset）可回溯。
    """
    from app.tasks.quality_check import run_quality_check_task

    task = run_quality_check_task.delay(str(kb_id))
    return QualityCheckTaskResponse(kb_id=kb_id, task_id=task.id, status="pending")


@router.get("/quality-check/tasks/{task_id}")
async def get_quality_check_task(task_id: str):
    """[admin] 轮询自动化质量门禁任务状态。"""
    from app.tasks.celery_app import celery_app

    result = celery_app.AsyncResult(task_id)
    return {
        "task_id": task_id,
        "status": result.state,
        "result": result.result if result.successful() else None,
        "error": str(result.result.get("error")) if result.failed() and isinstance(result.result, dict) else None,
    }


@router.get("/{kb_id}", response_model=KBResponse)
async def get_kb(
    kb_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await KBService.get_kb(db, kb_id, current_user)


@router.patch("/{kb_id}", response_model=KBResponse)
async def update_kb(
    kb_id: UUID,
    data: KBUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await KBService.update_kb(db, kb_id, current_user, data)


@router.delete("/{kb_id}")
async def delete_kb(
    kb_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await KBService.delete_kb(db, kb_id, current_user)
    return {"message": "Knowledge base deleted"}


@router.get("/{kb_id}/stats", response_model=KBStatsResponse)
async def get_kb_stats(
    kb_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await KBService.check_kb_access(db, kb_id, current_user)
    return await KBService.get_kb_stats(db, kb_id)


def _member_to_response(m: KBMember) -> dict:
    """KBMember（已 joinedload user）→ 含 username 的响应 dict。"""
    return {
        "id": m.id,
        "user_id": m.user_id,
        "username": m.user.username if m.user else None,
        "permission": m.permission,
        "created_at": m.created_at,
    }


@router.get("/{kb_id}/members", response_model=list[KBMemberResponse])
async def list_members(
    kb_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    members = await KBService.list_members(db, kb_id, current_user)
    return [_member_to_response(m) for m in members]


@router.post("/{kb_id}/members", response_model=KBMemberResponse)
async def add_member(
    kb_id: UUID,
    data: KBMemberAdd,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    member = await KBService.add_member(db, kb_id, current_user, data.user_id, data.permission)
    # 刷新以拿到 username
    fresh = (await db.execute(
        select(KBMember).options(joinedload(KBMember.user)).where(KBMember.id == member.id)
    )).scalar_one()
    return _member_to_response(fresh)


@router.delete("/{kb_id}/members/{user_id}")
async def remove_member(
    kb_id: UUID,
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await KBService.remove_member(db, kb_id, current_user, user_id)
    return {"message": "Member removed"}


@router.post("/sync-all-counts")
async def sync_all_counters(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Bulk-repair doc_count & chunk_count for all knowledge bases."""
    count = await KBService.sync_all_counters(db)
    return {"message": f"Synced {count} knowledge bases"}
