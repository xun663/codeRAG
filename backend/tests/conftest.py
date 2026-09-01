"""Shared fixtures and configuration for CodeRAG tests."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, PropertyMock
from typing import AsyncGenerator

import pytest

from app.core.learning.sm2 import SM2State, SM2Scheduler, Quality
from app.core.rag.intent_classifier import Intent
from app.core.rag.pipeline import RAGPipeline
from app.core.rag.query_standardizer import QueryStandardizer, StandardizationResult
from app.core.documents.pipeline import DocumentPipeline
from app.core.documents.chunkers.hybrid import HybridChunker
from app.core.documents.chunkers.base import BaseChunker
from app.core.documents.cleaners.pipeline import CleaningPipeline
from app.embedding.base import BaseEmbeddingModel
from app.llm.base import BaseLLMProvider
from app.vector_store.base import BaseVectorStore


# ── pytest-asyncio auto mode ──────────────────────────────────────────

def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "slow: marks tests as slow (skip with -m 'not slow')")


# ═════════════════════════════════════════════════════════════════════
#  Mock helpers
# ═════════════════════════════════════════════════════════════════════

class MockEmbeddingModel(BaseEmbeddingModel):
    """Deterministic fake embedding — returns unit vectors for testing."""

    _DIM = 384

    def __init__(self) -> None:
        super().__init__()
        self.embed_texts_calls: list[list[str]] = []
        self.embed_text_calls: list[str] = []

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.embed_texts_calls.append(texts)
        # Return sparse unit-ish vectors based on text hash for determinism
        result: list[list[float]] = []
        for t in texts:
            h = hash(t)
            vec = [float((h >> (i % 30)) & 1) / (i + 1) for i in range(self._DIM)]
            # Normalize to length ~1
            norm = sum(v * v for v in vec) ** 0.5 or 1.0
            result.append([v / norm for v in vec])
        return result

    async def embed_text(self, text: str) -> list[float]:
        self.embed_text_calls.append(text)
        r = await self.embed_texts([text])
        return r[0]

    def get_dimension(self) -> int:
        return self._DIM


class MockLLMProvider(BaseLLMProvider):
    """Fake LLM that returns predictable responses."""

    def __init__(self, response: str = "Mock answer based on the knowledge base.") -> None:
        self._response = response
        self.generate_calls: list[tuple[str, str | None]] = []

    async def generate(self, prompt: str, system_prompt: str | None = None, **kwargs) -> str:
        self.generate_calls.append((prompt, system_prompt))
        return self._response

    async def generate_stream(
        self, prompt: str, system_prompt: str | None = None, **kwargs
    ) -> AsyncGenerator[str, None]:
        self.generate_calls.append((prompt, system_prompt))
        for word in self._response.split():
            yield word + " "

    async def count_tokens(self, text: str) -> int:
        return len(text) // 4


class MockVectorStore(BaseVectorStore):
    """In-memory fake vector store for testing."""

    def __init__(self) -> None:
        self.collections: dict[str, list[dict]] = {}
        self.create_calls: list[str] = []
        self.add_calls: list[tuple[str, list[str], list[list[float]], list[str], list[dict] | None]] = []
        self.search_calls: list[tuple[str, list[float], int, dict | None]] = []

    async def create_collection(self, name: str) -> None:
        self.create_calls.append(name)
        if name not in self.collections:
            self.collections[name] = []

    async def delete_collection(self, name: str) -> None:
        self.collections.pop(name, None)

    async def add_vectors(
        self,
        collection_name: str,
        ids: list[str],
        embeddings: list[list[float]],
        documents: list[str],
        metadatas: list[dict] | None = None,
    ) -> None:
        self.add_calls.append((collection_name, ids, embeddings, documents, metadatas))
        if collection_name not in self.collections:
            self.collections[collection_name] = []
        for i, doc_id in enumerate(ids):
            self.collections[collection_name].append({
                "id": doc_id,
                "embedding": embeddings[i],
                "document": documents[i] if documents else "",
                "metadata": metadatas[i] if metadatas else {},
            })

    async def search(
        self,
        collection_name: str,
        query_embedding: list[float],
        k: int = 5,
        filter: dict | None = None,
    ) -> list[dict]:
        self.search_calls.append((collection_name, query_embedding, k, filter))
        items = self.collections.get(collection_name, [])
        results = []
        for item in items[:k]:
            results.append({
                "id": item["id"],
                "score": 0.85,
                "document": item["document"],
                "metadata": item["metadata"],
            })
        return results

    async def delete_by_ids(self, collection_name: str, ids: list[str]) -> None:
        if collection_name in self.collections:
            self.collections[collection_name] = [
                item for item in self.collections[collection_name]
                if item["id"] not in ids
            ]

    async def get_collection_stats(self, collection_name: str) -> dict:
        count = len(self.collections.get(collection_name, []))
        return {"name": collection_name, "count": count}

    async def get_all_documents(self, collection_name: str) -> list[dict]:
        items = self.collections.get(collection_name, [])
        return [
            {"id": item["id"], "document": item.get("document", ""), "metadata": item.get("metadata", {})}
            for item in items
        ]

    def set_search_results(self, results: list[dict]) -> None:
        """Override: inject results for the next search."""
        self._forced_results = results

    async def _do_search(self, *args, **kwargs) -> list[dict]:
        if hasattr(self, "_forced_results"):
            r = self._forced_results
            del self._forced_results
            return r
        return await self.search(*args, **kwargs)


# ═════════════════════════════════════════════════════════════════════
#  Fixtures: SM-2
# ═════════════════════════════════════════════════════════════════════

@pytest.fixture
def sm2_state() -> SM2State:
    """Fresh SM-2 state with default values."""
    return SM2State()


@pytest.fixture
def sm2_state_mature() -> SM2State:
    """SM-2 state that has progressed through several repetitions."""
    return SM2State(
        interval=30,
        ease_factor=2.5,
        repetitions=4,
        due_date=datetime.now() - timedelta(days=1),
        consecutive_correct=4,
        consecutive_wrong=0,
        total_attempts=10,
        total_correct=9,
        is_mastered=False,
    )


@pytest.fixture
def sm2_scheduler() -> SM2Scheduler:
    return SM2Scheduler()


# ═════════════════════════════════════════════════════════════════════
#  Fixtures: RAG Pipeline
# ═════════════════════════════════════════════════════════════════════

@pytest.fixture
def mock_embedding() -> MockEmbeddingModel:
    return MockEmbeddingModel()


@pytest.fixture
def mock_llm() -> MockLLMProvider:
    return MockLLMProvider()


@pytest.fixture
def mock_vector_store() -> MockVectorStore:
    return MockVectorStore()


@pytest.fixture
def rag_pipeline(mock_embedding, mock_llm, mock_vector_store) -> RAGPipeline:
    """RAGPipeline with all dependencies mocked."""
    pipeline = RAGPipeline.__new__(RAGPipeline)
    pipeline.embedding_model = mock_embedding
    pipeline.llm = mock_llm
    pipeline.vector_store = mock_vector_store
    return pipeline


@pytest.fixture
def standardizer() -> QueryStandardizer:
    return QueryStandardizer()


@pytest.fixture
def std_result_empty() -> StandardizationResult:
    """StandardizationResult with default/empty values."""
    return StandardizationResult(original="test query", cleaned="test query")


@pytest.fixture
def sample_chunks() -> list[dict]:
    """Sample retrieved chunks for pipeline tests."""
    return [
        {
            "id": "chunk-001",
            "score": 0.92,
            "document": "Python tuples are immutable sequences, typically used to store collections of heterogeneous data.",
            "metadata": {"doc_title": "Python Docs", "chunk_type": "text", "topic": "Tuples"},
        },
        {
            "id": "chunk-002",
            "score": 0.85,
            "document": "Tuples can be created with parentheses: t = (1, 2, 3).",
            "metadata": {"doc_title": "Python Docs", "chunk_type": "text", "topic": "Tuple Creation"},
        },
    ]


@pytest.fixture
def conversation_history() -> list[dict]:
    """Sample conversation history with at least one exchange."""
    return [
        {"role": "user", "content": "What is a tuple in Python?"},
        {"role": "assistant", "content": "A tuple is an immutable sequence type in Python."},
    ]


# ═════════════════════════════════════════════════════════════════════
#  Fixtures: Document Pipeline
# ═════════════════════════════════════════════════════════════════════

@pytest.fixture
def doc_pipeline(mock_embedding, mock_vector_store) -> DocumentPipeline:
    """DocumentPipeline with mocked dependencies and cleaner disabled."""
    pipeline = DocumentPipeline.__new__(DocumentPipeline)

    # Build parsers (using real ones since they're mostly file I/O)
    from app.core.documents.parsers.code_parser import CodeParser
    from app.core.documents.parsers.html_parser import HTMLParser
    from app.core.documents.parsers.markdown_parser import MarkdownParser
    from app.core.documents.parsers.pdf_parser import PDFParser

    pipeline.parsers = {
        "application/pdf": PDFParser(),
        "text/markdown": MarkdownParser(),
        "text/x-markdown": MarkdownParser(),
        "text/html": HTMLParser(),
        "text/plain": CodeParser(),
    }
    pipeline.cleaner = None  # Disable cleaning for most tests
    pipeline.chunker = HybridChunker()
    pipeline.embedding_model = mock_embedding
    pipeline.vector_store = mock_vector_store
    return pipeline


@pytest.fixture
def doc_pipeline_with_cleaner(mock_embedding, mock_vector_store) -> DocumentPipeline:
    """DocumentPipeline with cleaner enabled."""
    pipeline = DocumentPipeline.__new__(DocumentPipeline)

    from app.core.documents.parsers.code_parser import CodeParser
    from app.core.documents.parsers.html_parser import HTMLParser
    from app.core.documents.parsers.markdown_parser import MarkdownParser
    from app.core.documents.parsers.pdf_parser import PDFParser

    pipeline.parsers = {
        "application/pdf": PDFParser(),
        "text/markdown": MarkdownParser(),
        "text/x-markdown": MarkdownParser(),
        "text/html": HTMLParser(),
        "text/plain": CodeParser(),
    }
    pipeline.cleaner = CleaningPipeline()
    pipeline.chunker = HybridChunker()
    pipeline.embedding_model = mock_embedding
    pipeline.vector_store = mock_vector_store
    return pipeline


@pytest.fixture
def sample_markdown_file(tmp_path) -> str:
    """Create a temporary markdown file for document pipeline tests."""
    file_path = tmp_path / "test_doc.md"
    file_path.write_text(
        "# Python Tuples\n\n"
        "A tuple is a collection which is ordered and **immutable**.\n\n"
        "## Creating Tuples\n\n"
        "Tuples are written with round brackets:\n\n"
        "```python\n"
        "t = (1, 2, 3)\n"
        "print(t[0])  # Output: 1\n"
        "```\n\n"
        "## Tuple Methods\n\n"
        "Tuples have two built-in methods: `count()` and `index()`.\n\n"
        "> **Note:** Tuples are faster than lists for read-only data.\n",
        encoding="utf-8",
    )
    return str(file_path)


@pytest.fixture
def sample_python_file(tmp_path) -> str:
    """Create a temporary Python file for code parsing tests."""
    file_path = tmp_path / "sample.py"
    file_path.write_text(
        "def greet(name: str) -> str:\n"
        '    """Return a greeting."""\n'
        '    return f"Hello, {name}!"\n'
        "\n\n"
        "class Calculator:\n"
        '    """A simple calculator."""\n'
        "\n"
        "    def add(self, a: int, b: int) -> int:\n"
        "        return a + b\n"
        "\n"
        "    def subtract(self, a: int, b: int) -> int:\n"
        "        return a - b\n",
        encoding="utf-8",
    )
    return str(file_path)


@pytest.fixture
def sample_text_file(tmp_path) -> str:
    """Create a temporary plain text file."""
    file_path = tmp_path / "notes.txt"
    file_path.write_text(
        "Python is a high-level programming language.\n\n"
        "It emphasizes code readability with its notable use of significant indentation.\n\n"
        "Python supports multiple programming paradigms, including:\n"
        "- Procedural\n"
        "- Object-oriented\n"
        "- Functional programming\n",
        encoding="utf-8",
    )
    return str(file_path)
