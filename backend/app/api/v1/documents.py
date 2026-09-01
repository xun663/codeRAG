"""Document endpoints."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.middleware.auth import get_current_user
from app.models.user import User
from app.schemas.common import PaginatedResponse
from app.schemas.document import (
    DocumentImportURL, DocumentImportGit,
    DocumentResponse, DocumentChunkResponse, DocumentContentResponse,
)
from app.services.document_service import DocumentService
from app.services.kb_service import KBService

router = APIRouter(prefix="/kbs/{kb_id}/documents", tags=["documents"])


@router.get("", response_model=PaginatedResponse[DocumentResponse])
async def list_documents(
    kb_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await KBService.check_kb_access(db, kb_id, current_user)
    docs, total = await DocumentService.list_documents(db, kb_id, page, page_size)
    return PaginatedResponse(
        items=docs, total=total, page=page, page_size=page_size,
        pages=(total + page_size - 1) // page_size,
    )


@router.post("/upload", response_model=DocumentResponse, status_code=201)
async def upload_file(
    kb_id: UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await KBService.check_kb_write_access(db, kb_id, current_user)
    return await DocumentService.upload_file(db, kb_id, file)


@router.post("/upload-many", response_model=list[DocumentResponse], status_code=201)
async def upload_files(
    kb_id: UUID,
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await KBService.check_kb_write_access(db, kb_id, current_user)
    return await DocumentService.upload_files(db, kb_id, files)


@router.post("/from-url", response_model=DocumentResponse, status_code=201)
async def import_from_url(
    kb_id: UUID,
    data: DocumentImportURL,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await KBService.check_kb_write_access(db, kb_id, current_user)
    return await DocumentService.import_from_url(db, kb_id, data)


@router.post("/from-git", response_model=DocumentResponse, status_code=201)
async def import_from_git(
    kb_id: UUID,
    data: DocumentImportGit,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await KBService.check_kb_write_access(db, kb_id, current_user)
    return await DocumentService.import_from_git(db, kb_id, data)


@router.get("/{doc_id}", response_model=DocumentResponse)
async def get_document(
    kb_id: UUID,
    doc_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await KBService.check_kb_access(db, kb_id, current_user)
    return await DocumentService.get_document(db, doc_id)


@router.delete("/{doc_id}")
async def delete_document(
    kb_id: UUID,
    doc_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await KBService.check_kb_write_access(db, kb_id, current_user)
    await DocumentService.delete_document(db, doc_id)
    return {"message": "Document deleted"}


@router.get("/{doc_id}/chunks", response_model=list[DocumentChunkResponse])
async def list_chunks(
    kb_id: UUID,
    doc_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await KBService.check_kb_access(db, kb_id, current_user)
    return await DocumentService.get_document_chunks(db, doc_id)


@router.get("/{doc_id}/content", response_model=DocumentContentResponse)
async def get_content(
    kb_id: UUID,
    doc_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await KBService.check_kb_access(db, kb_id, current_user)
    return await DocumentService.get_document_content(db, doc_id)
