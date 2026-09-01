"""Evaluation metrics — Document-level (primary) + Chunk-level (auxiliary).

Design:
  - Document-level metrics are the PRIMARY indicators for RAG quality.
  - Chunk-level metrics are SECONDARY for fine-grained monitoring.
  - All functions are pure; no side effects, no DB access.

Metric hierarchy for thesis:
  Core:  Doc Hit Rate@K, Doc MRR, NDCG@K
  Aux:   Chunk Recall@K, Chunk Hit Rate@K
"""
from __future__ import annotations

import math


def compute_metrics(qa_pairs: list, results: list[dict], k: int = 5) -> dict:
    """Batch compute all metrics (document-level + chunk-level) over an eval run.

    Args:
        qa_pairs: List of EvalQAPair objects. Must have
            ``relevant_doc_ids`` (primary) and/or ``ground_truth_chunk_ids`` (aux).
        results: List of pipeline result dicts. Each must have ``sources`` list
            with ``chunk_id`` and ``doc_id`` (or ``metadata.doc_id``).
        k: Top-k cutoff.

    Returns:
        dict with avg_doc_hit, avg_doc_mrr, avg_ndcg, avg_chunk_recall, total.
    """
    total = len(qa_pairs)
    if total == 0:
        return {
            "avg_doc_hit_rate": 0.0, "avg_doc_mrr": 0.0, "avg_ndcg": 0.0,
            "avg_chunk_recall": 0.0, "total": 0,
        }

    doc_hit_sum = 0.0
    doc_mrr_sum = 0.0
    ndcg_sum = 0.0
    chunk_recall_sum = 0.0

    for pair, result in zip(qa_pairs, results):
        retrieved = result.get("sources", [])
        retrieved_ids = [s.get("chunk_id", "") for s in retrieved]
        retrieved_docs = [
            s.get("metadata", {}).get("doc_id", "")
            if isinstance(s.get("metadata"), dict)
            else s.get("doc_id", "")
            for s in retrieved
        ]

        # ── Document-level (primary) ─────────────────────────────
        doc_ids = getattr(pair, "relevant_doc_ids", None) or []
        doc_ids_str = [str(did) for did in doc_ids] if doc_ids else []
        if doc_ids_str:
            doc_hit_sum += doc_hit_at_k(retrieved_docs, doc_ids_str, k)
            doc_mrr_sum += doc_mrr(retrieved_docs, doc_ids_str)
            ndcg_sum += ndcg_at_k(retrieved_docs, doc_ids_str, k)

        # ── Chunk-level (auxiliary) ──────────────────────────────
        gt_ids = getattr(pair, "ground_truth_chunk_ids", None) or pair.expected_chunk_ids or []
        expected_ids = [str(cid) for cid in gt_ids]
        if expected_ids:
            chunk_recall_sum += chunk_recall_at_k(retrieved_ids, expected_ids, k)

    n = max(1, total)
    return {
        "avg_doc_hit_rate": round(doc_hit_sum / n, 4),
        "avg_doc_mrr": round(doc_mrr_sum / n, 4),
        "avg_ndcg": round(ndcg_sum / n, 4),
        "avg_chunk_recall": round(chunk_recall_sum / n, 4),
        "total": total,
    }


# ═════════════════════════════════════════════════════════════════════
#  Document-level metrics (PRIMARY for RAG)
# ═════════════════════════════════════════════════════════════════════


def doc_hit_at_k(
    retrieved_doc_ids: list[str],
    expected_doc_ids: list[str],
    k: int = 5,
) -> float:
    """Document Hit Rate@K.

    Whether the top-K results contain at least one relevant document.
    For RAG this is the most practical metric — a single correct document
    is enough for the LLM to produce a grounded answer.

    Formula: 1 if |retrieved_docs[:K] ∩ expected_docs| > 0 else 0
    Range: [0.0, 1.0]
    """
    if not expected_doc_ids:
        return 0.0
    return 1.0 if set(retrieved_doc_ids[:k]) & set(expected_doc_ids) else 0.0


def doc_mrr(
    retrieved_doc_ids: list[str],
    expected_doc_ids: list[str],
) -> float:
    """Document Mean Reciprocal Rank.

    The reciprocal rank of the *first* relevant document in the result list.
    Measures how early the user (or LLM) encounters the correct document.

    Formula: 1 / rank_of_first_relevant_doc
    Range: [0.0, 1.0]
    """
    if not expected_doc_ids:
        return 0.0
    for rank, doc_id in enumerate(retrieved_doc_ids, start=1):
        if doc_id in expected_doc_ids:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(
    retrieved_doc_ids: list[str],
    expected_doc_ids: list[str],
    k: int = 5,
) -> float:
    """NDCG@K — Normalised Discounted Cumulative Gain.

    Rewards ranking multiple relevant documents early. This is the most
    discriminating metric when configs differ mainly in *ordering* rather
    than which documents appear.

    NOTE: Each expected doc counts only once (first occurrence) to avoid
    inflating scores from duplicate ChromaDB entries of the same doc.

    Formula: DCG / IDCG, where DCG = Σ relevance_i / log₂(i+1)
    Range: [0.0, 1.0]
    """
    if not expected_doc_ids:
        return 0.0

    expected_set = set(expected_doc_ids)
    counted: set[str] = set()
    dcg = 0.0
    for i, doc_id in enumerate(retrieved_doc_ids[:k]):
        if doc_id in expected_set and doc_id not in counted:
            dcg += 1.0 / math.log2(i + 2)
            counted.add(doc_id)

    ideal_count = min(len(expected_set), k)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_count))
    return dcg / idcg if idcg > 0 else 0.0


# ═════════════════════════════════════════════════════════════════════
#  Chunk-level metrics (AUXILIARY for fine-grained monitoring)
# ═════════════════════════════════════════════════════════════════════


def chunk_recall_at_k(
    retrieved_chunk_ids: list[str],
    expected_chunk_ids: list[str],
    k: int = 5,
) -> float:
    """Chunk Recall@K.

    What fraction of the ground-truth chunks appear in the top-K results.
    This is a strict, fine-grained metric that penalises chunk-boundary
    mismatches even when the correct document is found.

    Formula: |retrieved_chunks[:K] ∩ expected_chunks| / |expected_chunks|
    Range: [0.0, 1.0]

    Note: For RAG evaluation this is an AUXILIARY metric. The primary
    metric should be doc-level, because the LLM can answer from any
    chunk within the correct document.
    """
    if not expected_chunk_ids:
        return 0.0
    matched = set(retrieved_chunk_ids[:k]) & set(expected_chunk_ids)
    return len(matched) / len(expected_chunk_ids)


def chunk_hit_at_k(
    retrieved_chunk_ids: list[str],
    expected_chunk_ids: list[str],
    k: int = 5,
) -> float:
    """Chunk Hit Rate@K — at least one expected chunk in top-K."""
    if not expected_chunk_ids:
        return 0.0
    return 1.0 if set(retrieved_chunk_ids[:k]) & set(expected_chunk_ids) else 0.0
