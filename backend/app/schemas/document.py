"""Document schemas."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class DocumentImportURL(BaseModel):
    url: str
    title: str | None = None


class DocumentImportGit(BaseModel):
    repo_url: str
    branch: str = "main"
    paths: list[str] | None = None  # Specific paths to import, None = all


class DocumentResponse(BaseModel):
    id: UUID
    kb_id: UUID
    title: str
    source_type: str
    source_url: str | None
    file_path: str | None
    file_size: int | None
    mime_type: str | None
    doc_hash: str | None
    word_count: int | None
    status: str
    error_message: str | None
    version: int
    metadata_json: dict
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DocumentChunkResponse(BaseModel):
    id: UUID
    doc_id: UUID
    chunk_index: int
    content_preview: str | None
    token_count: int | None
    chunk_type: str
    metadata_json: dict
    created_at: datetime

    model_config = {"from_attributes": True}


class DocumentContentResponse(BaseModel):
    id: UUID
    title: str
    content: str
    source_type: str
    metadata_json: dict
