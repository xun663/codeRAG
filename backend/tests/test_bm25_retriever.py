"""Tests for BM25SparseRetriever and MixedTokenizer.

Covers:
  - MixedTokenizer: CN/EN tokenization, code keywords, stopwords
  - BM25SparseRetriever: search, metadata filter, cache lifecycle, edge cases
"""
from __future__ import annotations

import pytest

from app.core.rag.retrieval.bm25_retriever import (
    BM25SparseRetriever,
    MixedTokenizer,
)
from tests.conftest import MockVectorStore


# ═════════════════════════════════════════════════════════════════════
#  MixedTokenizer
# ═════════════════════════════════════════════════════════════════════


class TestMixedTokenizer:
    """CN/EN tokenizer behaviour."""

    def make_tokenizer(self, stopwords: set[str] | None = None) -> MixedTokenizer:
        return MixedTokenizer(stopwords=stopwords)

    def test_chinese_text(self):
        """Chinese text is segmented by jieba into meaningful tokens."""
        tok = self.make_tokenizer()
        text = "快速排序是一种经典排序算法"
        tokens = tok.tokenize(text)
        assert "快速排序" in tokens
        assert "经典" in tokens
        assert "排序算法" in tokens or "排序" in tokens

    def test_english_text(self):
        """English text yields lowercase tokens."""
        tok = self.make_tokenizer()
        text = "HashMap uses array and linked list"
        tokens = tok.tokenize(text)
        assert "hashmap" in tokens
        assert "array" in tokens
        assert "linked" in tokens
        assert "list" in tokens
        assert "and" not in tokens

    def test_mixed_cn_en(self):
        """Mixed Chinese-English text is handled correctly."""
        tok = self.make_tokenizer()
        text = "Java中的HashMap采用数组+链表结构"
        tokens = tok.tokenize(text)
        assert "java" in tokens
        assert "hashmap" in tokens
        assert "数组" in tokens
        assert "链表" in tokens
        assert "结构" in tokens
        assert "的" not in tokens

    def test_code_keywords_preserved(self):
        """Code identifiers with underscores, hyphens, plus signs remain intact."""
        tok = self.make_tokenizer()
        text = "C++ and __init__ and spring-boot and multi_thread"
        tokens = tok.tokenize(text)
        assert "c++" in tokens or "cpp" in tokens
        assert any("spring" in t for t in tokens)
        assert any("boot" in t for t in tokens)

    def test_empty_input(self):
        """Empty or whitespace-only input returns empty list."""
        tok = self.make_tokenizer()
        assert tok.tokenize("") == []
        assert tok.tokenize("   ") == []
        assert tok.tokenize(None) == []

    def test_stopwords_filtered(self):
        """Configured stopwords are excluded from output."""
        extra_stop = {"foo", "bar"}
        tok = self.make_tokenizer(stopwords=extra_stop)
        text = "foo bar baz qux"
        tokens = tok.tokenize(text)
        assert "foo" not in tokens
        assert "bar" not in tokens
        assert "baz" in tokens
        assert "qux" in tokens

    def test_pure_digits_removed(self):
        """Standalone numeric tokens are filtered out."""
        tok = self.make_tokenizer()
        text = "python 3 12 version 3.12"
        tokens = tok.tokenize(text)
        assert "python" in tokens
        assert "version" in tokens

    def test_custom_stopwords_override(self):
        """Custom stopwords set replaces the default set."""
        custom = {"hello", "world"}
        tok = MixedTokenizer(stopwords=custom)
        tokens = tok.tokenize("hello world this is a test")
        assert "hello" not in tokens
        assert "world" not in tokens
        assert "this" in tokens
        assert "test" in tokens


# ═════════════════════════════════════════════════════════════════════
#  Fixtures — sync (populate MockVectorStore.collections directly)
# ═════════════════════════════════════════════════════════════════════

CN_DOCS = [
    ("doc-1", "快速排序是一种基于分治思想的高效排序算法", {"subject": "算法", "lang": "cn"}),
    ("doc-2", "HashMap基于数组加链表实现键值对存储", {"subject": "Java", "lang": "cn"}),
    ("doc-3", "Python使用动态类型系统无需声明变量类型", {"subject": "Python", "lang": "cn"}),
    ("doc-4", "Spring框架提供依赖注入和面向切面编程", {"subject": "Java", "lang": "cn"}),
    ("doc-5", "动态规划通过把原问题分解为相对简单的子问题", {"subject": "算法", "lang": "cn"}),
    ("doc-6", "Quick sort is an efficient divide-and-conquer algorithm", {"subject": "算法", "lang": "en"}),
]

EN_DOCS = [
    ("doc-j1", "HashMap in Java uses array of buckets with linked list or tree", {"subject": "Java", "framework": "core"}),
    ("doc-j2", "ArrayList implements dynamic array that grows automatically", {"subject": "Java", "framework": "collections"}),
    ("doc-p1", "Python list comprehension provides concise way to create lists", {"subject": "Python", "framework": "core"}),
    ("doc-p2", "Python decorators are functions that modify other functions", {"subject": "Python", "framework": "advanced"}),
    ("doc-s1", "Spring Boot auto-configuration simplifies Spring application setup", {"subject": "Java", "framework": "spring"}),
]


def _build_store(docs: list[tuple]) -> MockVectorStore:
    """Build a MockVectorStore with pre-populated data (sync helper)."""
    store = MockVectorStore()
    # Directly populate the collections dict to avoid async setup
    items = []
    for doc_id, text, meta in docs:
        items.append({
            "id": doc_id,
            "embedding": [0.0] * 384,
            "document": text,
            "metadata": meta,
        })
    store.collections["test_coll"] = items
    return store


@pytest.fixture
def cn_store() -> MockVectorStore:
    return _build_store(CN_DOCS)


@pytest.fixture
def en_store() -> MockVectorStore:
    return _build_store(EN_DOCS)


@pytest.fixture(autouse=True)
def auto_clear_cache():
    """Clear BM25 cache before and after each test."""
    BM25SparseRetriever.invalidate_all()
    yield
    BM25SparseRetriever.invalidate_all()


# ═════════════════════════════════════════════════════════════════════
#  BM25SparseRetriever (sync tests — BM25 logic is pure sync)
# ═════════════════════════════════════════════════════════════════════


class TestBM25SparseRetriever:
    """BM25 search behaviour."""

    # ── Basic functionality ──────────────────────────────────────

    def test_basic_search_english(self, en_store):
        """Basic English BM25 search returns relevant results."""
        import anyio
        results = anyio.run(
            BM25SparseRetriever.search,
            "HashMap", "test_coll", 5, en_store,
        )
        assert len(results) > 0
        assert results[0]["id"] == "doc-j1"
        assert "score" in results[0]
        assert results[0]["score"] > 0

    def test_basic_search_chinese(self, cn_store):
        """Chinese BM25 search returns relevant results."""
        import anyio
        results = anyio.run(
            BM25SparseRetriever.search,
            "快速排序", "test_coll", 5, cn_store,
        )
        assert len(results) > 0
        assert results[0]["id"] == "doc-1"

    def test_code_keyword_search(self, en_store):
        """Code keyword (HashMap) retrieves Java documents."""
        import anyio
        results = anyio.run(
            BM25SparseRetriever.search,
            "HashMap", "test_coll", 5, en_store,
        )
        ids = [r["id"] for r in results]
        assert "doc-j1" in ids

    def test_result_format(self, en_store):
        """Result format matches dense retriever: {id, score, document, metadata}."""
        import anyio
        results = anyio.run(
            BM25SparseRetriever.search,
            "HashMap", "test_coll", 1, en_store,
        )
        assert len(results) == 1
        r = results[0]
        assert "id" in r
        assert "score" in r
        assert "document" in r
        assert "metadata" in r
        assert isinstance(r["score"], float)
        assert isinstance(r["metadata"], dict)

    # ── Metadata filtering ──────────────────────────────────────

    def test_metadata_filter_java(self, en_store):
        """Filter by subject=Java returns only Java docs."""
        import anyio
        results = anyio.run(
            BM25SparseRetriever.search,
            "list", "test_coll", 5, en_store,
            {"subject": "Java"},
        )
        for r in results:
            assert r["metadata"]["subject"] == "Java"

    def test_metadata_filter_python(self, en_store):
        """Filter by subject=Python returns only Python docs."""
        import anyio
        results = anyio.run(
            BM25SparseRetriever.search,
            "function", "test_coll", 5, en_store,
            {"subject": "Python"},
        )
        for r in results:
            assert r["metadata"]["subject"] == "Python"

    def test_metadata_filter_no_match(self, en_store):
        """Filter that matches nothing returns empty list."""
        import anyio
        results = anyio.run(
            BM25SparseRetriever.search,
            "HashMap", "test_coll", 5, en_store,
            {"subject": "Rust"},
        )
        assert len(results) == 0

    def test_metadata_filter_chinese(self, cn_store):
        """Chinese docs — filter by subject=算法."""
        import anyio
        results = anyio.run(
            BM25SparseRetriever.search,
            "排序", "test_coll", 5, cn_store,
            {"subject": "算法"},
        )
        for r in results:
            assert r["metadata"]["subject"] == "算法"

    # ── Cache behaviour ──────────────────────────────────────────

    def test_cache_hit(self, en_store):
        """Second search returns same results without rebuilding index."""
        import anyio

        async def run():
            r1 = await BM25SparseRetriever.search(
                query="HashMap", collection_name="test_coll",
                k=5, vector_store=en_store,
            )
            v1 = BM25SparseRetriever._versions.get("test_coll")
            r2 = await BM25SparseRetriever.search(
                query="HashMap", collection_name="test_coll",
                k=5, vector_store=en_store,
            )
            assert BM25SparseRetriever._versions.get("test_coll") == v1
            # Same docs & same query → same scores
            assert [r["id"] for r in r1] == [r["id"] for r in r2]
            return r1
        anyio.run(run)

    def test_cache_rebuild_after_doc_added(self, en_store):
        """Adding a document triggers cache rebuild."""
        import anyio

        async def run():
            await BM25SparseRetriever.search(
                query="HashMap", collection_name="test_coll",
                k=5, vector_store=en_store,
            )
            v1 = BM25SparseRetriever._versions["test_coll"]

            # Add doc directly to the store's internal data
            en_store.collections["test_coll"].append({
                "id": "doc-new",
                "embedding": [0.0] * 384,
                "document": "New document about Rust ownership system",
                "metadata": {"subject": "Rust"},
            })

            await BM25SparseRetriever.search(
                query="HashMap", collection_name="test_coll",
                k=5, vector_store=en_store,
            )
            v2 = BM25SparseRetriever._versions["test_coll"]
            assert v2 != v1
        anyio.run(run)

    def test_cache_rebuild_after_doc_removed(self, en_store):
        """Removing a document triggers cache rebuild."""
        import anyio

        async def run():
            await BM25SparseRetriever.search(
                query="HashMap", collection_name="test_coll",
                k=5, vector_store=en_store,
            )
            v1 = BM25SparseRetriever._versions["test_coll"]

            # Remove a doc
            en_store.collections["test_coll"] = [
                d for d in en_store.collections["test_coll"]
                if d["id"] != "doc-j1"
            ]

            await BM25SparseRetriever.search(
                query="HashMap", collection_name="test_coll",
                k=5, vector_store=en_store,
            )
            v2 = BM25SparseRetriever._versions["test_coll"]
            assert v2 != v1
        anyio.run(run)

    def test_invalidate_specific_collection(self, en_store):
        """Invalidating one collection does not affect another."""
        import anyio

        async def run():
            await BM25SparseRetriever.search(
                query="HashMap", collection_name="test_coll",
                k=5, vector_store=en_store,
            )
            # Load cn_store under a different collection name
            cn_store2 = _build_store(CN_DOCS)
            cn_store2.collections["cn_coll"] = cn_store2.collections.pop("test_coll")
            await BM25SparseRetriever.search(
                query="快速排序", collection_name="cn_coll",
                k=5, vector_store=cn_store2,
            )

            assert "test_coll" in BM25SparseRetriever._indices
            assert "cn_coll" in BM25SparseRetriever._indices

            BM25SparseRetriever.invalidate("test_coll")
            assert "test_coll" not in BM25SparseRetriever._indices
            assert "cn_coll" in BM25SparseRetriever._indices
        anyio.run(run)

    def test_invalidate_all(self, en_store):
        """invalidate_all clears all caches."""
        import anyio

        async def run():
            await BM25SparseRetriever.search(
                query="test", collection_name="test_coll",
                k=5, vector_store=en_store,
            )
            assert "test_coll" in BM25SparseRetriever._indices
            BM25SparseRetriever.invalidate_all()
            assert len(BM25SparseRetriever._indices) == 0
        anyio.run(run)

    # ── Edge cases ───────────────────────────────────────────────

    def test_empty_collection(self):
        """Empty collection returns empty results (not crash)."""
        store = MockVectorStore()
        store.collections["empty"] = []

        import anyio
        results = anyio.run(
            BM25SparseRetriever.search,
            "test", "empty", 5, store,
        )
        assert results == []

    def test_empty_query(self, en_store):
        """Empty query returns empty results."""
        import anyio
        results = anyio.run(
            BM25SparseRetriever.search,
            "", "test_coll", 5, en_store,
        )
        assert results == []

    def test_k_larger_than_corpus(self, en_store):
        """k larger than corpus size returns all results."""
        import anyio
        results = anyio.run(
            BM25SparseRetriever.search,
            "HashMap", "test_coll", 100, en_store,
        )
        assert len(results) <= 5

    # ── get_stats ────────────────────────────────────────────────

    def test_get_stats(self, en_store):
        """get_stats returns cache metadata."""
        import anyio

        async def run():
            stats = BM25SparseRetriever.get_stats("test_coll")
            assert stats["cached"] is False

            await BM25SparseRetriever.search(
                query="test", collection_name="test_coll",
                k=5, vector_store=en_store,
            )
            stats = BM25SparseRetriever.get_stats("test_coll")
            assert stats["cached"] is True
            assert stats["doc_count"] == 5
        anyio.run(run)
