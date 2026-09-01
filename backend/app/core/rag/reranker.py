"""Cross-encoder re-ranker for hybrid RAG — semantic precision refinement.

Plugs into the pipeline **after** RRF fusion:

    Dense Retrieval + BM25 Sparse Retrieval → RRF Fusion → Cross-Encoder Rerank → Top-K

Architecture::

    CrossEncoderReranker      — singleton-managed CrossEncoder wrapper
        ├── rerank()          — public API: score & reorder (query, candidates)
        ├── load_model()      — explicit model (re)load / switch
        └── get_model_info()  — runtime inspection
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

# Force offline mode to prevent HuggingFace network calls (model is cached locally).
# Without this, CrossEncoder load hangs on HF update check when offline.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from app.config import settings

logger = logging.getLogger(__name__)


class CrossEncoderReranker:
    """Cross-encoder re-ranker with singleton model management.

    - Lazy-loads model on first ``rerank()`` call (or explicit ``load_model()``).
    - Cached as singleton — subsequent calls reuse the loaded model.
    - Auto-detects GPU (CUDA / MPS); falls back to CPU.
    - Graceful degradation: returns input unchanged on any error.
    - Supports hot-switching model via ``load_model(model_name)``.
    """

    _instance: CrossEncoderReranker | None = None
    _model: Any = None       # sentence_transformers.CrossEncoder
    _model_name: str | None = None

    def __new__(cls) -> CrossEncoderReranker:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    # ── Public API ─────────────────────────────────────────────────

    async def rerank(
        self,
        query: str,
        documents: list[dict],
        top_k: int,
        model_name: str | None = None,
    ) -> list[dict]:
        """Re-rank documents by (query, document) cross-encoder relevance score.

        Args:
            query: Original user query.
            documents: List of ``{id, document, metadata}`` dicts (RRF output).
            top_k: Number of results to return after re-ranking.
            model_name: Optional model override (defaults to ``settings.rerank_model``).

        Returns:
            Re-ranked list with ``rerank_score`` added to each dict,
            truncated to ``top_k``.
            Falls back to input ``documents[:top_k]`` on any error.
        """
        if not documents:
            return []

        model_name = model_name or settings.rerank_model

        try:
            model = self._get_model(model_name)
        except Exception as exc:
            logger.warning("Reranker model load failed (%s); using RRF fallback", exc)
            return documents[:top_k]

        pairs = [(query, d["document"]) for d in documents if d.get("document")]

        if not pairs:
            return documents[:top_k]

        try:
            scores: list[float] = await asyncio.to_thread(
                model.predict,
                pairs,
                batch_size=settings.rerank_batch_size,
                show_progress_bar=False,
            )
        except Exception as exc:
            logger.warning("Reranker predict failed (%s); using RRF fallback", exc)
            return documents[:top_k]

        # Attach score & sort (copy to avoid mutating input)
        scored = []
        for i, doc in enumerate(documents):
            new_doc = dict(doc)
            new_doc["rerank_score"] = float(scores[i]) if i < len(scores) else 0.0
            scored.append(new_doc)

        scored.sort(key=lambda x: x["rerank_score"], reverse=True)
        return scored[:top_k]

    def load_model(self, model_name: str) -> bool:
        """Explicitly load (or switch) a cross-encoder model.

        Returns ``True`` on success, ``False`` on failure.
        The previous model (if any) is discarded.
        """
        try:
            self._load_model_impl(model_name)
            return True
        except Exception as exc:
            logger.error("Failed to load reranker model '%s': %s", model_name, exc)
            self._model = None
            self._model_name = None
            return False

    def get_model_info(self) -> dict:
        """Return loaded model metadata (for monitoring / admin)."""
        return {
            "loaded": self._model is not None,
            "model_name": self._model_name,
        }

    # ── Internal: model lifecycle ──────────────────────────────────

    def _get_model(self, model_name: str):
        """Return cached model or lazy-load it."""
        if self._model is not None and self._model_name == model_name:
            return self._model
        self._load_model_impl(model_name)
        return self._model

    def _load_model_impl(self, model_name: str) -> None:
        """Instantiate ``sentence_transformers.CrossEncoder``."""
        from sentence_transformers import CrossEncoder

        device = self._detect_device()
        logger.info("Loading reranker model '%s' on %s ...", model_name, device)
        self._model = CrossEncoder(model_name, device=device, trust_remote_code=True)
        self._model_name = model_name
        logger.info("Reranker model '%s' loaded", model_name)

    @staticmethod
    def _detect_device() -> str:
        """Auto-detect best available device."""
        try:
            import torch
            if torch.cuda.is_available():
                return "cuda"
            if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                return "mps"
        except ImportError:
            pass
        return "cpu"
