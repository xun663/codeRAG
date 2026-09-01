"""Abstract vector store interface."""
from __future__ import annotations

from abc import ABC, abstractmethod


class BaseVectorStore(ABC):
    """Abstract base for vector store implementations."""

    @abstractmethod
    async def create_collection(self, name: str) -> None:
        """Create a new collection."""
        ...

    @abstractmethod
    async def delete_collection(self, name: str) -> None:
        """Delete a collection."""
        ...

    @abstractmethod
    async def add_vectors(
        self,
        collection_name: str,
        ids: list[str],
        embeddings: list[list[float]],
        documents: list[str],
        metadatas: list[dict] | None = None,
    ) -> None:
        """Add vectors with documents and metadata."""
        ...

    @abstractmethod
    async def search(
        self,
        collection_name: str,
        query_embedding: list[float],
        k: int = 5,
        filter: dict | None = None,
    ) -> list[dict]:
        """Search for similar vectors. Returns list of {id, score, document, metadata}."""
        ...

    @abstractmethod
    async def delete_by_ids(self, collection_name: str, ids: list[str]) -> None:
        """Delete vectors by their IDs."""
        ...

    @abstractmethod
    async def get_collection_stats(self, collection_name: str) -> dict:
        """Get collection statistics."""
        ...

    @abstractmethod
    async def get_all_documents(
        self,
        collection_name: str,
    ) -> list[dict]:
        """Get all documents from a collection.

        Returns:
            list[dict]: Each entry has {"id": str, "document": str, "metadata": dict}
        """
        ...
