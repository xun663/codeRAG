"""Full document processing pipeline."""
from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from app.config import settings
from app.core.documents.parsers.code_parser import CodeParser
from app.core.documents.parsers.html_parser import HTMLParser
from app.core.documents.parsers.markdown_parser import MarkdownParser
from app.core.documents.parsers.pdf_parser import PDFParser
from app.core.documents.chunkers.hybrid import HybridChunker
from app.core.documents.cleaners.pipeline import CleaningPipeline
from app.embedding.factory import get_embedding_model
from app.vector_store.factory import get_vector_store


class DocumentPipeline:
    """Orchestrates: parse → chunk → embed → index."""

    def __init__(self):
        self.parsers = {
            "application/pdf": PDFParser(),
            "text/markdown": MarkdownParser(),
            "text/x-markdown": MarkdownParser(),
            "text/html": HTMLParser(),
            "text/plain": CodeParser(),
        }
        self.cleaner = CleaningPipeline() if settings.cleaning_enabled else None
        self.chunker = HybridChunker()
        self.embedding_model = get_embedding_model()
        self.vector_store = get_vector_store()

    async def process_file(
        self, file_path: str, kb_id: str, mime_type: str | None = None,
        doc_id: str | None = None, doc_title: str | None = None,
    ) -> dict:
        """Process a single file through the full pipeline.

        Args:
            file_path: Path to the file on disk.
            kb_id: Knowledge base ID (for collection naming).
            mime_type: MIME type of the file.
            doc_id: Document ID (stored in chunk metadata for provenance).
            doc_title: Document title (displayed in citations).
        """
        path = Path(file_path)
        mime_type = mime_type or self._guess_mime(path)

        # 1. Parse
        parser = self.parsers.get(mime_type, MarkdownParser())
        text = await parser.parse(str(path))

        # 2. Compute hash
        doc_hash = hashlib.sha256(text.encode()).hexdigest()

        # 3. Detect language
        lang = self._detect_language(path)

        # 4. Clean (if enabled)
        cleaning_stats = {"enabled": False, "before_chars": 0, "after_chars": 0, "removed_chars": 0}
        if self.cleaner:
            cleaned, stats = await self.cleaner.clean(text, {
                "file_type": mime_type, "language": lang, "source_file": path.name,
            })
            cleaning_stats = stats.summary()
            text = cleaned

        # 5. Chunk
        chunks = await self.chunker.split(text, {
            "file_extension": path.suffix,
            "language": lang,
            "mime_type": mime_type,
            "source_file": path.name,
        })

        # 5. Embed — 标题增强：embedding 文本 = "doc_title —— content"
        #    （标题词参与语义对齐，提升 query↔chunk 匹配；存储仍为纯 content）
        title = doc_title or path.name
        chunk_texts = [c["content"] for c in chunks]
        embed_texts = [f"{title} —— {c}" for c in chunk_texts]
        embeddings = await self.embedding_model.embed_texts(embed_texts)

        # 6. Index in vector store
        collection = f"kb_{kb_id}"
        chunk_ids = [str(uuid.uuid4()) for _ in chunks]
        metadatas = [
            {
                **c.get("metadata", {}),
                "chunk_type": c.get("chunk_type", "text"),
                "token_count": c.get("token_count", 0),
                "doc_title": doc_title or path.name,           # ← document title for citations
                "kb_id": kb_id,                                 # ← source KB
                "doc_id": doc_id or "",                         # ← source document ID
            }
            for c in chunks
        ]

        await self.vector_store.create_collection(collection)
        await self.vector_store.add_vectors(
            collection_name=collection,
            ids=chunk_ids,
            embeddings=embeddings,
            documents=chunk_texts,
            metadatas=metadatas,
        )

        return {
            "doc_hash": doc_hash,
            "word_count": len(text.split()),
            "cleaning": cleaning_stats,
            "chunks": [
                {
                    "id": cid,
                    "content": text,
                    "chunk_type": meta.get("chunk_type", "text"),
                    "metadata": meta,
                    "token_count": meta.get("token_count", 0),
                }
                for cid, text, meta in zip(chunk_ids, chunk_texts, metadatas)
            ],
        }

    async def process_url(self, url: str, kb_id: str, title: str | None = None,
                         doc_id: str | None = None) -> dict:
        """Process a URL through the pipeline.

        Args:
            url: The URL to fetch and process.
            kb_id: Knowledge base ID.
            title: Document title (displayed in citations).
            doc_id: Document ID (stored in chunk metadata for provenance).
        """
        from app.core.documents.parsers.html_parser import HTMLParser
        html_parser = HTMLParser()
        text = await html_parser.parse_url(url)

        # Clean (if enabled)
        cleaning_stats = {"enabled": False, "before_chars": 0, "after_chars": 0, "removed_chars": 0}
        if self.cleaner:
            cleaned, stats = await self.cleaner.clean(text, {
                "file_type": "text/html", "source_url": url,
            })
            cleaning_stats = stats.summary()
            text = cleaned

        chunks = await self.chunker.split(text, {"source_url": url, "title": title or url})

        # Embed — 标题增强（与 process_file 一致）
        title = title or url
        chunk_texts = [c["content"] for c in chunks]
        embed_texts = [f"{title} —— {c}" for c in chunk_texts]
        embeddings = await self.embedding_model.embed_texts(embed_texts)

        collection = f"kb_{kb_id}"
        chunk_ids = [str(uuid.uuid4()) for _ in chunks]
        metadatas = [
            {
                **c.get("metadata", {}),
                "chunk_type": c.get("chunk_type", "text"),
                "doc_title": title,
                "source_url": url,
                "kb_id": kb_id,
                "doc_id": doc_id or "",
            }
            for c in chunks
        ]

        await self.vector_store.create_collection(collection)
        await self.vector_store.add_vectors(
            collection_name=collection,
            ids=chunk_ids,
            embeddings=embeddings,
            documents=chunk_texts,
            metadatas=metadatas,
        )

        return {
            "doc_hash": hashlib.sha256(text.encode()).hexdigest(),
            "word_count": len(text.split()),
            "cleaning": cleaning_stats,
            "chunks": [
                {"id": cid, "content": t, "chunk_type": m.get("chunk_type", "text"),
                 "metadata": m, "token_count": m.get("token_count", 0)}
                for cid, t, m in zip(chunk_ids, chunk_texts, metadatas)
            ],
        }

    def _guess_mime(self, path: Path) -> str:
        ext = path.suffix.lower()
        mime_map = {
            ".pdf": "application/pdf",
            ".md": "text/markdown",
            ".py": "text/x-python",
            ".js": "text/javascript",
            ".ts": "text/x-typescript",
            ".java": "text/x-java",
            ".go": "text/x-go",
            ".rs": "text/x-rust",
            ".cpp": "text/x-c++",
            ".c": "text/x-c",
            ".html": "text/html",
            ".txt": "text/plain",
        }
        return mime_map.get(ext, "text/plain")

    def _detect_language(self, path: Path) -> str:
        ext = path.suffix.lower()
        lang_map = {
            ".py": "python", ".js": "javascript", ".ts": "typescript",
            ".jsx": "javascript", ".tsx": "typescript",
            ".java": "java", ".go": "go", ".rs": "rust",
            ".c": "c", ".cpp": "cpp", ".h": "c",
            ".cs": "csharp", ".rb": "ruby", ".php": "php",
            ".swift": "swift", ".kt": "kotlin",
        }
        return lang_map.get(ext, "text")
