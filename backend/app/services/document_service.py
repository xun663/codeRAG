"""Document service."""
from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.exceptions import ConflictException, NotFoundException
from app.models.document import Document, DocumentChunk
from app.schemas.document import DocumentImportURL, DocumentImportGit
from app.core.documents.pipeline import DocumentPipeline
from app.services.kb_service import KBService


class DocumentService:
    @staticmethod
    async def list_documents(db: AsyncSession, kb_id, page: int = 1, page_size: int = 20) -> tuple[list[Document], int]:
        uid = uuid.UUID(str(kb_id)) if not isinstance(kb_id, uuid.UUID) else kb_id
        count_r = await db.execute(select(func.count(Document.id)).where(Document.kb_id == uid))
        total = count_r.scalar_one()
        offset = (page - 1) * page_size
        r = await db.execute(select(Document).where(Document.kb_id == uid).order_by(Document.created_at.desc()).offset(offset).limit(page_size))
        return list(r.scalars().all()), total

    @staticmethod
    async def upload_file(db: AsyncSession, kb_id, file: UploadFile) -> Document:
        upload_dir = Path(settings.upload_dir) / str(kb_id)
        upload_dir.mkdir(parents=True, exist_ok=True)
        file_path = upload_dir / f"{uuid.uuid4().hex}_{file.filename}"
        content = await file.read()
        file_path.write_bytes(content)

        doc_hash = hashlib.sha256(content).hexdigest()

        # Dedup: check if document with same hash already exists in this KB
        existing = await db.execute(
            select(Document).where(Document.doc_hash == doc_hash, Document.kb_id == kb_id)
        )
        if existing.scalar_one_or_none():
            raise ConflictException("Document already exists in this knowledge base")

        doc = Document(
            id=uuid.uuid4(), kb_id=kb_id, title=file.filename or "Untitled",
            source_type="upload", file_path=str(file_path),
            file_size=len(content), mime_type=file.content_type,
            doc_hash=doc_hash,
            word_count=len(content.decode("utf-8", errors="replace").split()),
            status="processing",
        )
        db.add(doc)
        await db.flush()

        pipeline = DocumentPipeline()
        try:
            result = await pipeline.process_file(
                str(file_path), str(kb_id), file.content_type,
                doc_id=str(doc.id), doc_title=doc.title,
            )
            doc.status = "indexed"
            if result.get("cleaning"):
                doc.metadata_json = {**(doc.metadata_json or {}), "cleaning": result["cleaning"]}
            await DocumentService._save_chunks(db, doc.id, kb_id, result["chunks"])
            await KBService.sync_counters(db, kb_id)
            # 文档集变更 → 旧门禁结果失效（否则报告页显示脏指标）
            await KBService.invalidate_quality_gate(db, kb_id)
        except Exception as e:
            doc.status = "error"
            doc.error_message = str(e)
        await db.flush()
        return doc

    @staticmethod
    async def upload_files(db: AsyncSession, kb_id, files: list[UploadFile]) -> list[Document]:
        """批量上传：每个文件独立处理，单文件失败不中断整批。

        - 成功 → indexed 文档
        - 内容重复（dedup 冲突）→ 返回已存在的文档
        - 处理失败 → 返回 status=error 的占位文档（error_message 记录原因）
        """
        results: list[Document] = []
        for file in files:
            try:
                results.append(await DocumentService.upload_file(db, kb_id, file))
            except ConflictException:
                # 内容已在库中：找回已存在文档（upload_file 已消费 file 内容，需 seek 重置）
                await file.seek(0)
                content = await file.read()
                doc_hash = hashlib.sha256(content).hexdigest()
                r = await db.execute(
                    select(Document).where(Document.doc_hash == doc_hash, Document.kb_id == kb_id)
                )
                results.append(r.scalar_one())
            except Exception as e:
                err_doc = Document(
                    id=uuid.uuid4(), kb_id=kb_id, title=file.filename or "Untitled",
                    source_type="upload", file_size=0, status="error",
                    error_message=str(e)[:500],
                )
                results.append(err_doc)
        await db.flush()
        return results

    @staticmethod
    async def import_from_url(db: AsyncSession, kb_id, data: DocumentImportURL) -> Document:
        doc = Document(
            id=uuid.uuid4(), kb_id=kb_id, title=data.title or data.url,
            source_type="url", source_url=data.url, status="processing",
        )
        db.add(doc)
        await db.flush()
        pipeline = DocumentPipeline()
        try:
            result = await pipeline.process_url(data.url, str(kb_id), data.title, doc_id=str(doc.id))
            doc.status = "indexed"
            if result.get("cleaning"):
                doc.metadata_json = {**(doc.metadata_json or {}), "cleaning": result["cleaning"]}
            await DocumentService._save_chunks(db, doc.id, kb_id, result["chunks"])
            await KBService.sync_counters(db, kb_id)
            # 文档集变更 → 旧门禁结果失效（否则报告页显示脏指标）
            await KBService.invalidate_quality_gate(db, kb_id)
        except Exception as e:
            doc.status = "error"
            doc.error_message = str(e)
        await db.flush()
        return doc

    @staticmethod
    async def import_from_git(db: AsyncSession, kb_id, data: DocumentImportGit) -> Document:
        doc = Document(
            id=uuid.uuid4(), kb_id=kb_id, title=f"Git: {data.repo_url}",
            source_type="github" if "github" in data.repo_url else "gitlab",
            source_url=data.repo_url, status="pending",
            metadata_json={"branch": data.branch, "paths": data.paths},
        )
        db.add(doc)
        await db.flush()
        try:
            from app.tasks.git_sync import sync_git_repo
            sync_git_repo.delay(data.repo_url, data.branch, str(kb_id), data.paths)
            doc.status = "processing"
            # 文档集变更 → 旧门禁结果失效
            await KBService.invalidate_quality_gate(db, kb_id)
        except Exception:
            doc.status = "pending"
        await db.flush()
        return doc

    @staticmethod
    async def get_document(db: AsyncSession, doc_id) -> Document:
        uid = uuid.UUID(str(doc_id)) if not isinstance(doc_id, uuid.UUID) else doc_id
        r = await db.execute(select(Document).where(Document.id == uid))
        doc = r.scalar_one_or_none()
        if not doc:
            raise NotFoundException("Document not found")
        return doc

    @staticmethod
    async def delete_document(db: AsyncSession, doc_id) -> None:
        doc = await DocumentService.get_document(db, doc_id)
        kb_id = doc.kb_id

        # Clean up vector store before DB deletion
        try:
            from app.vector_store.factory import get_vector_store
            store = get_vector_store()
            chunks = await DocumentService.get_document_chunks(db, doc_id)
            vector_ids = [str(c.id) for c in chunks if c.vector_id]
            if vector_ids:
                await store.delete_by_ids(f"kb_{kb_id}", vector_ids)
        except Exception:
            pass  # Best-effort: vector orphan is acceptable, DB must be correct

        await db.delete(doc)
        await db.flush()
        await KBService.sync_counters(db, kb_id)
        # 文档集变更 → 旧门禁结果失效
        await KBService.invalidate_quality_gate(db, kb_id)

    @staticmethod
    async def get_document_chunks(db: AsyncSession, doc_id) -> list[DocumentChunk]:
        uid = uuid.UUID(str(doc_id)) if not isinstance(doc_id, uuid.UUID) else doc_id
        r = await db.execute(select(DocumentChunk).where(DocumentChunk.doc_id == uid).order_by(DocumentChunk.chunk_index))
        return list(r.scalars().all())

    @staticmethod
    async def get_document_content(db: AsyncSession, doc_id) -> dict:
        doc = await DocumentService.get_document(db, doc_id)
        content = ""
        if doc.file_path and os.path.exists(doc.file_path):
            content = Path(doc.file_path).read_text(encoding="utf-8", errors="replace")
        return {"id": doc.id, "title": doc.title, "content": content, "source_type": doc.source_type, "metadata_json": doc.metadata_json}

    @staticmethod
    async def _save_chunks(db: AsyncSession, doc_id, kb_id, chunks: list[dict]) -> None:
        for i, c in enumerate(chunks):
            chunk = DocumentChunk(
                id=uuid.UUID(c.get("id", str(uuid.uuid4()))),
                doc_id=doc_id, kb_id=kb_id, chunk_index=i,
                content=c["content"], content_preview=c["content"][:200],
                token_count=c.get("token_count", 0),
                vector_id=c.get("id", str(uuid.uuid4())),
                chunk_type=c.get("chunk_type", "text"),
                metadata_json=c.get("metadata", {}),
            )
            db.add(chunk)
        await db.flush()
