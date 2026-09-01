"""BM25 sparse retriever for hybrid RAG — CN/EN tokenizer with jieba.

Architecture::

    BM25SparseRetriever
        ├── MixedTokenizer      — CN jieba + EN regex + stopwords
        ├── _IndexManager       — per-collection BM25 cache (hash-keyed)
        ├── search()            — public API
        └── invalidate()        — lifecycle hook
"""
from __future__ import annotations

import hashlib
import re
from typing import ClassVar

from rank_bm25 import BM25Okapi


# ═════════════════════════════════════════════════════════════════════
#  Tokenizer
# ═════════════════════════════════════════════════════════════════════

# Default stopwords for both Chinese and English
DEFAULT_STOPWORDS: frozenset[str] = frozenset({
    # English
    "a", "an", "the", "is", "are", "was", "were", "be", "been",
    "i", "you", "he", "she", "it", "we", "they",
    "this", "that", "these", "those",
    "in", "on", "at", "to", "for", "of", "with", "by", "from", "as",
    "and", "or", "but", "not", "no",
    "do", "does", "did", "have", "has", "had",
    "can", "could", "will", "would", "shall", "should", "may", "might",
    "if", "then", "else", "when", "where", "why", "how",
    "what", "which", "who", "whom", "whose",
    "about", "into", "over", "after", "before", "between", "under",
    "just", "also", "very", "too", "more", "most", "some", "any",
    "each", "every", "both", "all", "few", "many", "much",
    "here", "there", "up", "down", "out", "off", "above", "below",
    "get", "got", "use", "used", "using", "like",
    "one", "two", "first", "second", "last",
    # Chinese single-character noise
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人",
    "都", "一", "个", "上", "也", "很", "到", "说", "要", "去",
    "你", "会", "着", "没有", "看", "好", "自己", "这",
    "他", "她", "它", "们", "那", "什么", "怎么", "为什么",
    "因为", "所以", "但是", "然而", "如果", "虽然",
    "可以", "能够", "应该", "必须", "可能",
    "从", "把", "被", "让", "向", "与", "对",
})


class MixedTokenizer:
    """Mixed Chinese-English tokenizer backed by jieba.

    Handles:
      - Chinese text segmentation via jieba
      - English / numeric tokens via regex
      - Code identifiers (keeps ``_``, ``-``, ``+`` within tokens)
      - Stopword removal
      - Lowercase normalisation
    """

    def __init__(self, stopwords: set[str] | None = None):
        import jieba as _jieba
        self._jieba = _jieba
        self.stopwords = frozenset(stopwords) if stopwords is not None else DEFAULT_STOPWORDS

        # Pre-warm jieba with common technical terms
        for term in _TECH_TERMS:
            _jieba.add_word(term)

    def tokenize(self, text: str) -> list[str]:
        """Tokenize mixed CN/EN text into a list of normalised tokens."""
        if not text:
            return []
        text = text.lower()

        tokens: list[str] = []

        # 1. Chinese segments via jieba
        cn_parts = self._jieba.cut(text, cut_all=False)
        for part in cn_parts:
            part = part.strip()
            if not part:
                continue
            # Keep Chinese characters
            if re.search(r"[一-鿿]", part):
                if part not in self.stopwords:
                    tokens.append(part)
            else:
                # Non-Chinese — will be handled by regex step below
                # but we still collect longer multi-word phrases from jieba
                if len(part) > 3 and part not in self.stopwords:
                    tokens.append(part)

        # 2. English / code tokens via regex on the original lowercased text
        for match in re.finditer(r"[a-z0-9_+\-]+", text):
            token = match.group(0)
            # Skip pure digits
            if token.isdigit():
                continue
            # Skip short fragments (single letter, single digit)
            if len(token) < 2 and not token.isalpha():
                continue
            if token not in self.stopwords:
                tokens.append(token)

        # 3. Deduplicate while preserving order
        seen: set[str] = set()
        deduped: list[str] = []
        for t in tokens:
            if t not in seen:
                seen.add(t)
                deduped.append(t)
        return deduped


# Common technical terms to add to jieba dictionary
_TECH_TERMS: list[str] = [
    # Programming languages
    "java", "python", "javascript", "typescript", "cpp", "c++", "golang",
    "rust", "kotlin", "swift", "ruby", "php", "scala", "dart",
    # Frameworks & libraries
    "spring", "springboot", "django", "flask", "fastapi", "react", "vue",
    "angular", "tensorflow", "pytorch", "numpy", "pandas",
    # CS concepts
    "hashmap", "arraylist", "linkedlist", "hashset",
    "多线程", "线程安全", "线程池", "锁", "同步", "异步",
    "面向对象", "继承", "多态", "封装", "接口", "抽象类",
    "数据结构", "算法", "排序算法", "时间复杂度", "空间复杂度",
    "数据库", "索引", "事务", "表", "sql", "nosql",
    "快速排序", "归并排序", "冒泡排序", "二分查找", "动态规划",
    # Chinese tech terms
    "虚拟机", "垃圾回收", "内存管理", "类加载", "反射",
    "中间件", "微服务", "分布式", "缓存", "消息队列",
    "容器", "docker", "kubernetes", "k8s", "devops",
    # Java-specific
    "jvm", "jdk", "jre", "maven", "gradle", "tomcat", "servlet",
    "mybatis", "hibernate", "zookeeper", "kafka", "redis",
]

# ═════════════════════════════════════════════════════════════════════
#  BM25 Sparse Retriever
# ═════════════════════════════════════════════════════════════════════


class _BM25Index:
    """Holds a BM25Okapi instance together with its document metadata."""

    __slots__ = ("bm25", "docs", "tokenized_corpus")

    def __init__(self, bm25: BM25Okapi, docs: list[dict], tokenized_corpus: list[list[str]]):
        self.bm25 = bm25
        self.docs = docs
        self.tokenized_corpus = tokenized_corpus


def _compute_docs_hash(docs: list[dict]) -> str:
    """Deterministic hash of document IDs for cache versioning."""
    ids = sorted(doc["id"] for doc in docs)
    return hashlib.sha256("|".join(ids).encode("utf-8")).hexdigest()[:16]


class BM25SparseRetriever:
    """BM25 sparse retrieval with per-collection cache and metadata filtering.

    Usage::

        results = await BM25SparseRetriever.search(
            query="快速排序",
            collection_name="kb_xxx",
            k=5,
            vector_store=chroma_store,
            filter={"subject": "Java"},
        )
    """

    _tokenizer: MixedTokenizer | None = None
    _indices: ClassVar[dict[str, _BM25Index]] = {}
    _versions: ClassVar[dict[str, str]] = {}  # collection_name → docs_hash

    @classmethod
    def _get_tokenizer(cls) -> MixedTokenizer:
        """Lazy-init tokenizer (avoids jieba import at module load time)."""
        if cls._tokenizer is None:
            cls._tokenizer = MixedTokenizer()
        return cls._tokenizer

    # ── Public API ─────────────────────────────────────────────────

    @classmethod
    async def search(
        cls,
        query: str,
        collection_name: str,
        k: int,
        vector_store,
        filter: dict | None = None,
    ) -> list[dict]:
        """BM25 search with automatic index build / refresh.

        Args:
            query: Raw query string (mixed CN/EN).
            collection_name: ChromaDB collection name (e.g. ``kb_{uuid}``).
            k: Number of results to return.
            vector_store: A ``BaseVectorStore`` implementation.
            filter: Optional metadata filter dict (post-filter on results).

        Returns:
            list[dict]: Each entry has ``{id, score, document, metadata}``,
                        matching the dense retriever output format.
        """
        # 1. Get or build BM25 index
        try:
            index = await cls._get_or_build_index(collection_name, vector_store)
        except _EmptyCorpusError:
            return []

        # 2. Tokenize query
        tokenized_query = cls._get_tokenizer().tokenize(query)

        if not tokenized_query:
            return []

        # 3. Score
        scores = index.bm25.get_scores(tokenized_query)

        # 4. Pair docs with scores and sort
        doc_scores = list(enumerate(scores))
        doc_scores.sort(key=lambda x: x[1], reverse=True)

        # 5. Apply optional metadata filter
        results: list[dict] = []
        for idx, score in doc_scores:
            doc = index.docs[idx]
            if filter and not cls._matches_filter(doc["metadata"], filter):
                continue
            results.append({
                "id": doc["id"],
                "score": float(score),
                "document": doc["document"],
                "metadata": doc["metadata"],
            })
            if len(results) >= k:
                break

        return results

    @classmethod
    def invalidate(cls, collection_name: str) -> None:
        """Force index rebuild on the next search for this collection.

        Call this when documents are deleted from a KB or when the
        KB itself is deleted.
        """
        cls._indices.pop(collection_name, None)
        cls._versions.pop(collection_name, None)

    @classmethod
    def invalidate_all(cls) -> None:
        """Clear all cached BM25 indices."""
        cls._indices.clear()
        cls._versions.clear()

    @classmethod
    def get_stats(cls, collection_name: str) -> dict:
        """Return cache statistics for a collection (for monitoring)."""
        index = cls._indices.get(collection_name)
        version = cls._versions.get(collection_name)
        return {
            "collection": collection_name,
            "cached": index is not None,
            "version": version,
            "doc_count": len(index.docs) if index else 0,
            "vocab_size": len(index.bm25.idf) if index and hasattr(index.bm25, "idf") else 0,
        }

    # ── Internal: index management ─────────────────────────────────

    @classmethod
    async def _get_or_build_index(cls, collection_name: str, vector_store) -> _BM25Index:
        """Return cached index if still fresh, else rebuild from ChromaDB."""
        # Fetch current document list
        docs = await vector_store.get_all_documents(collection_name)
        if not docs:
            cls._indices.pop(collection_name, None)
            cls._versions.pop(collection_name, None)
            raise _EmptyCorpusError(f"Collection '{collection_name}' has no documents")

        current_hash = _compute_docs_hash(docs)

        # Cache hit?
        cached = cls._indices.get(collection_name)
        if cached is not None and cls._versions.get(collection_name) == current_hash:
            return cached

        # Build new index
        tokenized_corpus = [cls._get_tokenizer().tokenize(d["document"]) for d in docs]
        bm25 = BM25Okapi(tokenized_corpus, k1=1.5, b=0.75)

        index = _BM25Index(bm25=bm25, docs=docs, tokenized_corpus=tokenized_corpus)
        cls._indices[collection_name] = index
        cls._versions[collection_name] = current_hash
        return index

    # ── Internal: metadata filtering ───────────────────────────────

    @staticmethod
    def _matches_filter(metadata: dict, filter: dict) -> bool:
        """Check if a document's metadata matches the filter.

        Supports exact-value matching (``{"subject": "Java"}``).
        All filter keys must match for the document to pass.
        """
        for key, value in filter.items():
            if metadata.get(key) != value:
                return False
        return True


class _EmptyCorpusError(Exception):
    """Raised when a collection has no documents to index."""
    pass
