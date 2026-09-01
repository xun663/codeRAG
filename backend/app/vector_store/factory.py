"""Vector store factory."""
from __future__ import annotations

from functools import lru_cache

from app.vector_store.base import BaseVectorStore
from app.vector_store.chroma_store import ChromaVectorStore


@lru_cache()
def get_vector_store() -> BaseVectorStore:
    """Get vector store instance (singleton)."""
    return ChromaVectorStore()
