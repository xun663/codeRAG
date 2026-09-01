"""ChromaDB vector store implementation."""
from __future__ import annotations

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.config import settings
from app.vector_store.base import BaseVectorStore


class ChromaVectorStore(BaseVectorStore):
    def __init__(self):
        self.client = self._create_client()

    @staticmethod
    def _create_client():
        """Create ChromaDB client with fallback chain: Persistent → HTTP → In-Memory."""
        persist_path = settings.chroma_persist_path
        if persist_path:
            try:
                import os
                os.makedirs(persist_path, exist_ok=True)
                return chromadb.PersistentClient(
                    path=persist_path,
                    settings=ChromaSettings(anonymized_telemetry=False),
                )
            except Exception:
                pass
        try:
            return chromadb.HttpClient(
                host=settings.chroma_host,
                port=settings.chroma_port,
            )
        except Exception:
            # Fallback to in-memory for dev
            return chromadb.Client(
                ChromaSettings(anonymized_telemetry=False)
            )

    async def create_collection(self, name: str) -> None:
        try:
            self.client.create_collection(name=name)
        except Exception:
            pass  # Collection already exists

    async def delete_collection(self, name: str) -> None:
        try:
            self.client.delete_collection(name=name)
        except Exception:
            pass

    async def add_vectors(
        self,
        collection_name: str,
        ids: list[str],
        embeddings: list[list[float]],
        documents: list[str],
        metadatas: list[dict] | None = None,
    ) -> None:
        collection = self.client.get_or_create_collection(name=collection_name)
        collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )

    async def search(
        self,
        collection_name: str,
        query_embedding: list[float],
        k: int = 5,
        filter: dict | None = None,
    ) -> list[dict]:
        try:
            collection = self.client.get_collection(name=collection_name)
        except Exception:
            return []

        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=k,
            where=filter,
        )

        formatted = []
        if results.get("ids") and results["ids"][0]:
            for i, doc_id in enumerate(results["ids"][0]):
                formatted.append({
                    "id": doc_id,
                    "score": 1.0 - results["distances"][0][i] if results.get("distances") else 0.0,
                    "document": results.get("documents", [[None]])[0][i] if results.get("documents") else None,
                    "metadata": results.get("metadatas", [[{}]])[0][i] if results.get("metadatas") else {},
                })
        return formatted

    async def delete_by_ids(self, collection_name: str, ids: list[str]) -> None:
        try:
            collection = self.client.get_collection(name=collection_name)
            collection.delete(ids=ids)
        except Exception:
            pass

    async def get_collection_stats(self, collection_name: str) -> dict:
        try:
            collection = self.client.get_collection(name=collection_name)
            return {
                "name": collection_name,
                "count": collection.count(),
            }
        except Exception:
            return {"name": collection_name, "count": 0, "error": "Collection not found"}

    async def get_all_documents(self, collection_name: str) -> list[dict]:
        """Fetch all documents from a ChromaDB collection."""
        try:
            collection = self.client.get_collection(name=collection_name)
        except Exception:
            return []
        all_data = collection.get(include=["documents", "metadatas"])
        results = []
        ids = all_data.get("ids", [])
        docs = all_data.get("documents", [])
        metas = all_data.get("metadatas", [])
        for i, doc_id in enumerate(ids):
            results.append({
                "id": doc_id,
                "document": docs[i] if i < len(docs) and docs[i] else "",
                "metadata": metas[i] if i < len(metas) and metas[i] else {},
            })
        return results
