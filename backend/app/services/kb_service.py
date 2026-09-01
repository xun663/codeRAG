"""Knowledge Base service."""
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.exceptions import ForbiddenException, NotFoundException
from app.models.document import Document, DocumentChunk
from app.models.knowledge_base import KBMember, KnowledgeBase
from app.models.user import User
from app.schemas.knowledge_base import KBCreate, KBUpdate


class KBService:
    @staticmethod
    async def create_kb(db: AsyncSession, user: User, data: KBCreate) -> KnowledgeBase:
        # 双层模型：platform 库（平台策展、质量门禁）仅系统 admin 可建；
        # 普通用户只能建 personal 库（隔离作用域，不进公共检索/评估）。
        requested_scope = data.scope or ("platform" if user.role == "admin" else "personal")
        if requested_scope == "platform" and user.role != "admin":
            raise ForbiddenException("Only admins can create platform knowledge bases")
        # 可见性：platform 库 admin 可调（默认 public）；personal 库强制私有（分享靠成员）
        if requested_scope == "platform":
            visibility = data.visibility or "public"
            if visibility == "shared":
                visibility = "public"
        else:
            visibility = "private"
        kb = KnowledgeBase(
            id=uuid.uuid4(), name=data.name, description=data.description,
            owner_id=user.id, kb_type=data.kb_type, visibility=visibility,
            scope=requested_scope,
            vector_db_name=f"kb_{uuid.uuid4().hex[:16]}",
        )
        db.add(kb)
        await db.flush()
        db.add(KBMember(id=uuid.uuid4(), kb_id=kb.id, user_id=user.id, permission="admin"))
        await db.flush()
        return kb

    @staticmethod
    async def get_kb(db: AsyncSession, kb_id, user: User) -> KnowledgeBase:
        kb = await KBService._get_kb_or_404(db, kb_id)
        await KBService.check_kb_access(db, kb_id, user)
        return kb

    @staticmethod
    async def check_kb_access(db: AsyncSession, kb_id, user: User) -> None:
        """Read access: owner/member, public platform KB, or system admin (governance)."""
        await KBService._check_read_permission(db, kb_id, user)

    @staticmethod
    def _check_platform_admin(kb: KnowledgeBase, user: User) -> None:
        """官方库（platform scope）仅系统 admin 可操作——不依赖成员关系，与出题权限一致。

        个人库走成员/owner 校验；官方库即使被 admin 加了成员，非 admin 角色也不得写。
        """
        if kb.scope == "platform" and user.role != "admin":
            raise ForbiddenException("仅管理员可操作官方知识库")

    @staticmethod
    async def check_kb_write_access(db: AsyncSession, kb_id, user: User) -> None:
        kb = await KBService._get_kb_or_404(db, kb_id)
        KBService._check_platform_admin(kb, user)
        await KBService._check_permission(db, kb_id, user.id, "write")

    @staticmethod
    async def list_kbs(db: AsyncSession, user: User, page: int = 1, page_size: int = 20) -> tuple[list[KnowledgeBase], int]:
        # 可见性：自己的 / 是成员的 / platform 库（非 private 公开，或 admin 治理）。
        # personal 库始终私有，只能 owner/成员看到。
        member_kb_ids = select(KBMember.kb_id).where(KBMember.user_id == user.id)
        visible = (
            (KnowledgeBase.owner_id == user.id)
            | KnowledgeBase.id.in_(member_kb_ids)
        )
        if user.role == "admin":
            # admin 看到全部 platform 库（含调试中的 private，便于调试后切回 public）
            visible = visible | (KnowledgeBase.scope == "platform")
        else:
            # 普通用户只看到 public 的 platform 库（private = 调试中，隐藏）
            visible = visible | ((KnowledgeBase.scope == "platform") & (KnowledgeBase.visibility != "private"))
        count_r = await db.execute(
            select(func.count(KnowledgeBase.id)).where(visible)
        )
        total = count_r.scalar_one()
        offset = (page - 1) * page_size
        result = await db.execute(
            select(KnowledgeBase).options(joinedload(KnowledgeBase.owner))
            .where(visible)
            .order_by(KnowledgeBase.updated_at.desc()).offset(offset).limit(page_size)
        )
        return list(result.unique().scalars().all()), total

    @staticmethod
    async def invalidate_quality_gate(db: AsyncSession, kb_id) -> None:
        """文档/分块变更后使旧门禁结果失效（否则报告页显示基于旧 chunk 的脏指标）。"""
        kb = await KBService._get_kb_or_404(db, kb_id)
        if kb.quality_status != "not_checked" or kb.quality_metrics_json:
            kb.quality_status = "not_checked"
            kb.quality_metrics_json = None
            await db.flush()

    @staticmethod
    async def update_kb(db: AsyncSession, kb_id, user: User, data: KBUpdate) -> KnowledgeBase:
        kb = await KBService._get_kb_or_404(db, kb_id)
        KBService._check_platform_admin(kb, user)
        await KBService._check_permission(db, kb_id, user.id, "admin")
        for key in ("name", "description", "visibility", "config_json"):
            val = getattr(data, key, None)
            if val is not None:
                setattr(kb, key, val)
        # 个人库强制私有（分享靠成员），任何试图改 public 的请求都被忽略
        if kb.scope != "platform":
            kb.visibility = "private"
        await db.flush()
        return kb

    @staticmethod
    async def delete_kb(db: AsyncSession, kb_id, user: User) -> None:
        kb = await KBService._get_kb_or_404(db, kb_id)
        KBService._check_platform_admin(kb, user)
        await KBService._check_permission(db, kb_id, user.id, "admin")
        # 级联删除关联的评估数据集（MySQL 外键约束，否则删库 500）
        from sqlalchemy import delete as sql_delete
        from app.models.feedback import EvalDataset, EvalQAPair, EvalResult
        ds_ids = (await db.execute(
            select(EvalDataset.id).where(EvalDataset.kb_id == kb_id)
        )).scalars().all()
        if ds_ids:
            pair_ids = (await db.execute(
                select(EvalQAPair.id).where(EvalQAPair.dataset_id.in_(ds_ids))
            )).scalars().all()
            if pair_ids:
                await db.execute(sql_delete(EvalResult).where(EvalResult.qa_pair_id.in_(pair_ids)))
            await db.execute(sql_delete(EvalQAPair).where(EvalQAPair.dataset_id.in_(ds_ids)))
            await db.execute(sql_delete(EvalDataset).where(EvalDataset.id.in_(ds_ids)))
        # Try to delete vector store collection
        try:
            import httpx
            from app.config import settings
            async with httpx.AsyncClient() as client:
                await client.post(f"http://{settings.chroma_host}:{settings.chroma_port}/api/v1/collections/kb_{kb_id}/delete")
        except Exception:
            pass
        await db.delete(kb)
        await db.flush()

    @staticmethod
    async def add_member(db: AsyncSession, kb_id, admin_user: User, target_user_id, permission: str = "read") -> KBMember:
        await KBService._check_permission(db, kb_id, admin_user.id, "admin")
        # Check user exists
        from sqlalchemy import select as s
        r = await db.execute(s(User).where(User.id == target_user_id))
        if not r.scalar_one_or_none():
            raise NotFoundException("User not found")
        # Check not already member
        r2 = await db.execute(select(KBMember).where(KBMember.kb_id == kb_id, KBMember.user_id == target_user_id))
        if r2.scalar_one_or_none():
            from app.exceptions import ConflictException
            raise ConflictException("User is already a member")
        member = KBMember(id=uuid.uuid4(), kb_id=kb_id, user_id=target_user_id, permission=permission)
        db.add(member)
        await db.flush()
        return member

    @staticmethod
    async def remove_member(db: AsyncSession, kb_id, admin_user: User, target_user_id) -> None:
        await KBService._check_permission(db, kb_id, admin_user.id, "admin")
        r = await db.execute(select(KBMember).where(KBMember.kb_id == kb_id, KBMember.user_id == target_user_id))
        member = r.scalar_one_or_none()
        if member:
            await db.delete(member)
            await db.flush()

    @staticmethod
    async def list_members(db: AsyncSession, kb_id, user: User) -> list[KBMember]:
        await KBService._check_permission(db, kb_id, user.id, "admin")
        r = await db.execute(select(KBMember).options(joinedload(KBMember.user)).where(KBMember.kb_id == kb_id))
        return list(r.unique().scalars().all())

    @staticmethod
    async def get_kb_stats(db: AsyncSession, kb_id) -> dict:
        r = await db.execute(select(func.count(Document.id)).where(Document.kb_id == kb_id))
        doc_count = r.scalar_one()
        r2 = await db.execute(select(func.count(DocumentChunk.id)).where(DocumentChunk.kb_id == kb_id))
        chunk_count = r2.scalar_one()
        r3 = await db.execute(select(func.sum(DocumentChunk.token_count)).where(DocumentChunk.kb_id == kb_id))
        total_tokens = r3.scalar() or 0
        return {
            "kb_id": kb_id, "doc_count": doc_count, "chunk_count": chunk_count,
            "total_tokens": int(total_tokens),
            "avg_chunk_size": round(total_tokens / chunk_count, 1) if chunk_count else 0,
        }

    @staticmethod
    async def build_quality_report(db: AsyncSession) -> list[dict]:
        """Aggregate per-KB quality data for the admin quality report.

        Combines: basic stats, cleaning stats (from doc.metadata_json),
        chunk structure stats (token/type distribution), and the latest
        quality-gate verdict.
        """
        kbs = (await db.execute(
            select(KnowledgeBase).order_by(KnowledgeBase.updated_at.desc())
        )).scalars().all()

        report = []
        for kb in kbs:
            docs = (await db.execute(
                select(Document).where(Document.kb_id == kb.id)
            )).scalars().all()

            # ── Cleaning stats aggregation ─────────────────────────
            cleaning = {
                "docs_with_cleaning": 0,
                "before_chars": 0, "after_chars": 0, "removed_chars": 0,
            }
            for d in docs:
                cl = (d.metadata_json or {}).get("cleaning") or {}
                if cl.get("enabled"):
                    cleaning["docs_with_cleaning"] += 1
                    cleaning["before_chars"] += cl.get("before_chars", 0) or 0
                    cleaning["after_chars"] += cl.get("after_chars", 0) or 0
                    cleaning["removed_chars"] += cl.get("removed_chars", 0) or 0
            if cleaning["before_chars"]:
                cleaning["removed_pct"] = round(
                    cleaning["removed_chars"] / cleaning["before_chars"] * 100, 1
                )

            # ── Chunk structure stats ──────────────────────────────
            rows = (await db.execute(
                select(
                    func.count(DocumentChunk.id),
                    func.coalesce(func.sum(DocumentChunk.token_count), 0),
                    DocumentChunk.chunk_type,
                )
                .where(DocumentChunk.kb_id == kb.id)
                .group_by(DocumentChunk.chunk_type)
            )).all()
            chunk_type_dist = {str(r[2] or "text"): int(r[0]) for r in rows}
            total_chunks = sum(int(r[0]) for r in rows)
            total_tokens = sum(int(r[1] or 0) for r in rows)

            # ── Latest gate verdict (drop per-pair details) ────────
            gate = None
            if kb.quality_metrics_json:
                gate = {
                    k: v for k, v in kb.quality_metrics_json.items()
                    if k != "per_pair"
                }

            # 用实际表计数而非可能过期的计数器字段（reindex/脚本重建后 kb.chunk_count 会失准）
            actual_doc_count = (await db.execute(
                select(func.count(Document.id)).where(Document.kb_id == kb.id)
            )).scalar_one()

            report.append({
                "kb_id": kb.id,
                "name": kb.name,
                "scope": kb.scope,
                "visibility": kb.visibility,
                "quality_status": kb.quality_status,
                "current_version": kb.current_version,
                "doc_count": actual_doc_count,
                "chunk_count": total_chunks,
                "cleaning": cleaning,
                "chunk_stats": {
                    "total_tokens": total_tokens,
                    "avg_tokens_per_chunk": round(total_tokens / total_chunks, 1) if total_chunks else 0,
                    "chunk_type_distribution": chunk_type_dist,
                },
                "gate": gate,
                "updated_at": kb.updated_at,
            })
        return report

    @staticmethod
    async def sync_counters(db: AsyncSession, kb_id) -> tuple[int, int]:
        """Recalculate and persist doc_count & chunk_count from real data."""
        doc_count = (await db.execute(
            select(func.count(Document.id)).where(Document.kb_id == kb_id)
        )).scalar_one()
        chunk_count = (await db.execute(
            select(func.count(DocumentChunk.id)).where(DocumentChunk.kb_id == kb_id)
        )).scalar_one()
        # Use direct UPDATE to minimise the race window between COUNT and write
        from sqlalchemy import update as sql_update
        await db.execute(
            sql_update(KnowledgeBase)
            .where(KnowledgeBase.id == kb_id)
            .values(doc_count=doc_count, chunk_count=chunk_count)
        )
        await db.flush()
        return doc_count, chunk_count

    @staticmethod
    async def sync_all_counters(db: AsyncSession) -> int:
        """Repair counters for all KBs; return how many were updated."""
        kbs = (await db.execute(select(KnowledgeBase))).scalars().all()
        updated = 0
        for kb in kbs:
            doc_c = (await db.execute(
                select(func.count(Document.id)).where(Document.kb_id == kb.id)
            )).scalar_one()
            chk_c = (await db.execute(
                select(func.count(DocumentChunk.id)).where(DocumentChunk.kb_id == kb.id)
            )).scalar_one()
            if kb.doc_count != doc_c or kb.chunk_count != chk_c:
                kb.doc_count = doc_c
                kb.chunk_count = chk_c
                updated += 1
        await db.flush()
        return updated

    # ── Internal helpers ─────────────────────────────────────
    @staticmethod
    async def _get_kb_or_404(db: AsyncSession, kb_id) -> KnowledgeBase:
        uid = uuid.UUID(str(kb_id)) if not isinstance(kb_id, uuid.UUID) else kb_id
        r = await db.execute(select(KnowledgeBase).options(joinedload(KnowledgeBase.owner)).where(KnowledgeBase.id == uid))
        kb = r.unique().scalar_one_or_none()
        if not kb:
            raise NotFoundException(f"Knowledge base '{kb_id}' not found")
        return kb

    @staticmethod
    async def _check_read_permission(db: AsyncSession, kb_id, user: User) -> KBMember | None:
        """Read-level access check（执行 visibility）。

        Allowed when any of:
          1. 系统 admin（全库只读治理，含调试中的私有 platform 库）
          2. platform 库 visibility=public（默认，全员可见）
          3. personal 库 visibility=public（全员可见）
          4. owner / 成员（read 或以上权限）——private 的 personal 库、调试中的 platform 库

        visibility 语义：public=全员可读；private=仅 admin / owner / 成员。
        """
        kb = await KBService._get_kb_or_404(db, kb_id)
        if user.role == "admin":
            return None
        if kb.visibility == "public":
            return None
        return await KBService._check_permission(db, kb_id, user.id, "read")

    @staticmethod
    async def _check_permission(db: AsyncSession, kb_id, user_id, required: str) -> KBMember:
        uid = uuid.UUID(str(user_id)) if not isinstance(user_id, uuid.UUID) else user_id
        r = await db.execute(select(KBMember).where(KBMember.kb_id == kb_id, KBMember.user_id == uid))
        member = r.scalar_one_or_none()
        hierarchy = {"read": 0, "write": 1, "admin": 2}
        if not member or hierarchy.get(member.permission, 0) < hierarchy.get(required, 0):
            raise ForbiddenException("Insufficient permissions")
        return member
