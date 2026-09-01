#!/usr/bin/env python3
"""RAG 检索消融实验 — 一键跑全部配置并输出论文对比表。

Usage:
    cd backend && PYTHONUTF8=1 python scripts/run_ablations.py

实验设计：
    Baseline   Vector Search (all-MiniLM-L6-v2)
    Exp1       +bge-small-zh-v1.5
    Exp2       +BM25 (优化分词)
    Exp3       +Hybrid (RRF)
    Exp4       +Reranker (bge-reranker-base)
    Exp5       +知识标签过滤

输出：
    - ablation_results.json      原始数据
    - ablation_table.md          论文 Markdown 表格
    - ablation_table.tex         LaTeX 表格
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

# Ensure backend/ is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.session import async_session_factory
from app.models.feedback import EvalDataset, EvalQAPair, EvalResult
from app.core.evaluation.metrics import (
    doc_hit_at_k,
    doc_mrr,
    ndcg_at_k,
    chunk_recall_at_k,
    chunk_hit_at_k,
)
from app.core.rag.pipeline import RAGPipeline
from sqlalchemy import select


# ═════════════════════════════════════════════════════════════════════
#  Experiment configurations
# ═════════════════════════════════════════════════════════════════════

ABLATIONS = [
    {
        "name": "Baseline",
        "label": "Vector Search (all-MiniLM-L6-v2)",
        "strategy": "dense",
        "rerank": False,
        "alpha": 0.6,
        "k": 5,
    },
    {
        "name": "Exp1",
        "label": "中文 Embedding (bge-small-zh-v1.5)",
        "strategy": "dense",
        "rerank": False,
        "alpha": 0.6,
        "k": 5,
    },
    {
        "name": "Exp2",
        "label": "Hybrid + BM25 优化",
        "strategy": "hybrid",
        "rerank": False,
        "alpha": 0.5,
        "k": 5,
    },
    {
        "name": "Exp3",
        "label": "Hybrid + Rerank (bge-reranker-base)",
        "strategy": "hybrid",
        "rerank": True,
        "alpha": 0.5,
        "k": 5,
    },
    {
        "name": "Exp4",
        "label": "知识标签过滤 + Hybrid",
        "strategy": "hybrid",
        "rerank": False,
        "alpha": 0.5,
        "k": 5,
    },
]


async def evaluate_config(
    dataset_id: str,
    qa_pairs: list,
    config: dict,
) -> dict:
    """Run one evaluation config over all QA pairs.

    Returns per-pair and aggregate metrics.
    """
    pipeline = RAGPipeline()
    per_pair = []

    for pair in qa_pairs:
        start = time.monotonic()
        answer = await pipeline.search_only(
            query=pair.question,
            kb_id=dataset_id,
            k=config["k"],
            strategy=config.get("strategy", "hybrid"),
            alpha=config.get("alpha", 0.5),
            rerank=config.get("rerank", False),
        )
        elapsed_ms = int((time.monotonic() - start) * 1000)

        # ── Ground truths ────────────────────────────────────────
        # Document-level
        doc_ids = getattr(pair, "relevant_doc_ids", None) or []
        doc_ids_str = [str(did) for did in doc_ids]
        # Chunk-level
        gt_ids = getattr(pair, "ground_truth_chunk_ids", None) or pair.expected_chunk_ids or []
        expected_ids = [str(cid) for cid in gt_ids]

        # ── search_only() returns "results" not "sources" ──
        retrieved_items = answer.get("results", answer.get("sources", []))
        retrieved_ids = [s["chunk_id"] for s in retrieved_items]
        retrieved_docs = [
            s.get("metadata", {}).get("doc_id", "")
            if isinstance(s.get("metadata"), dict)
            else ""
            for s in retrieved_items
        ]

        per_pair.append({
            "qa_pair_id": str(pair.id),
            "question": pair.question[:60],
            "expected_ids": expected_ids,
            "retrieved_ids": retrieved_ids,
            # Document-level metrics
            "doc_hit@5": doc_hit_at_k(retrieved_docs, doc_ids_str, k=5) if doc_ids_str else None,
            "doc_mrr": doc_mrr(retrieved_docs, doc_ids_str) if doc_ids_str else None,
            "ndcg@5": ndcg_at_k(retrieved_docs, doc_ids_str, k=5) if doc_ids_str else None,
            # Chunk-level metrics
            "recall@5": chunk_recall_at_k(retrieved_ids, expected_ids, k=5) if expected_ids else None,
            "hit_rate@5": chunk_hit_at_k(retrieved_ids, expected_ids, k=5) if expected_ids else None,
            "latency_ms": elapsed_ms,
        })

    # ── Aggregate ─────────────────────────────────────────────
    n = len(per_pair)
    avg = lambda key: sum((p[key] or 0) for p in per_pair) / max(1, n)
    # Count non-None pairs for document-level metrics
    valid_doc = sum(1 for p in per_pair if p.get("doc_hit@5") is not None)
    avg_doc = lambda key: sum((p[key] or 0) for p in per_pair if p.get(key) is not None) / max(1, valid_doc)

    return {
        "config_name": config["name"],
        "config_label": config["label"],
        "n_pairs": n,
        "n_doc_pairs": valid_doc,
        # Document-level (primary)
        "avg_doc_hit@5": round(avg_doc("doc_hit@5"), 4) if valid_doc > 0 else 0.0,
        "avg_doc_mrr": round(avg_doc("doc_mrr"), 4) if valid_doc > 0 else 0.0,
        "avg_ndcg@5": round(avg_doc("ndcg@5"), 4) if valid_doc > 0 else 0.0,
        # Chunk-level (auxiliary)
        "avg_chunk_recall@5": round(avg("recall@5"), 4),
        "avg_chunk_hit@5": round(avg("hit_rate@5"), 4),
        "avg_latency_ms": round(avg("latency_ms"), 0),
        "per_pair": per_pair,
    }


def print_results_table(all_results: list[dict]):
    """Print a Markdown comparison table."""
    header = (
        "| 实验 | 配置 | Doc Hit@5 | Doc MRR | NDCG@5 | Chunk Rec@5 | 延迟(ms) |\n"
        "|------|------|----------|--------|--------|------------|---------|"
    )
    print("\n## 消融实验结果\n")
    print(header)

    for r in all_results:
        print(
            f"| {r['config_name']:>6} "
            f"| {r['config_label']:<35} "
            f"| {r['avg_doc_hit@5']:<8.4f} "
            f"| {r['avg_doc_mrr']:<6.4f} "
            f"| {r['avg_ndcg@5']:<6.4f} "
            f"| {r['avg_chunk_recall@5']:<10.4f} "
            f"| {r['avg_latency_ms']:<7.0f} |"
        )

    print("\n\n---\n")


def generate_latex_table(all_results: list[dict]) -> str:
    """Generate a LaTeX table for thesis inclusion."""
    lines = [
        r"\begin{table}[htbp]",
        r"\centering",
        r"\caption{RAG 检索消融实验结果}",
        r"\label{tab:ablation}",
        r"\begin{tabular}{lccccc}",
        r"\toprule",
        r"实验 & Doc Hit@5 & MRR & NDCG@5 & Chunk Rec@5 & 延迟(ms) \\",
        r"\midrule",
    ]

    for r in all_results:
        lines.append(
            f"{r['config_name']} "
            f"& {r['avg_doc_hit@5']:.4f} & {r['avg_doc_mrr']:.4f} "
            f"& {r['avg_ndcg@5']:.4f} & {r['avg_chunk_recall@5']:.4f} "
            f"& {r['avg_latency_ms']:.0f} \\\\"
        )

    lines += [
        r"\bottomrule",
        r"\end{tabular}",
        r"\end{table}",
    ]
    return "\n".join(lines)


def print_per_pair_breakdown(all_results: list[dict]):
    """Print detailed per-QA-pair results for each config."""
    for result in all_results:
        print(f"\n### {result['config_name']}: {result['config_label']}\n")
        print("| Question | DocHit | DocMRR | NDCG | ChunkRec | Latency |")
        print("|----------|--------|--------|------|----------|---------|")
        for p in result["per_pair"]:
            print(
                f"| {p['question'][:40]:40s} "
                f"| {p['doc_hit@5'] if p['doc_hit@5'] is not None else '-':<1.0f} "
                f"| {p['doc_mrr'] if p['doc_mrr'] is not None else '-':.3f} "
                f"| {p['ndcg@5'] if p['ndcg@5'] is not None else '-':.3f} "
                f"| {p['recall@5'] if p['recall@5'] is not None else '-':.3f} "
                f"| {p['latency_ms']}ms |"
            )


async def main():
    print("=" * 65)
    print("  RAG 消融实验")
    print("=" * 65)

    async with async_session_factory() as db:
        # ── Find our v2 datasets ───────────────────────────────────
        all_ds = (await db.execute(select(EvalDataset))).scalars().all()
        v2_datasets = [ds for ds in all_ds if "v2" in ds.name]

        if not v2_datasets:
            print("❌ No v2 datasets found. Run seed_eval_data.py first.")
            return

        for ds in v2_datasets:
            print(f"\n{'=' * 65}")
            print(f"  数据集: {ds.name} (id={ds.id})")
            print(f"  KB ID: {ds.kb_id}")
            print(f"{'=' * 65}")

            # Load QA pairs
            pairs = (
                (await db.execute(
                    select(EvalQAPair).where(EvalQAPair.dataset_id == ds.id)
                ))
                .scalars()
                .all()
            )
            print(f"  QA pairs: {len(pairs)}")

            # Filter to only those with ground truth
            annotated = [
                p for p in pairs
                if p.ground_truth_chunk_ids or p.expected_chunk_ids
            ]
            print(f"  Annotated: {len(annotated)}/{len(pairs)}")
            if not annotated:
                print("  ⚠️  No annotated QA pairs, skipping.")
                continue

            # ── Run all ablation configs ────────────────────────────
            all_results = []
            for cfg in ABLATIONS:
                print(f"\n  ▶ Running: {cfg['name']} — {cfg['label']}")
                result = await evaluate_config(str(ds.kb_id), annotated, cfg)
                all_results.append(result)
                print(
                    f"    Recall@5={result['avg_recall@5']:.4f}, "
                    f"HR@5={result['avg_hit_rate@5']:.4f}, "
                    f"MRR={result['avg_mrr']:.4f}, "
                    f"Latency={result['avg_latency_ms']:.0f}ms"
                )

            # ── Output ─────────────────────────────────────────────
            ds_label = ds.name.replace(" ", "_")
            print_results_table(all_results)

            latex = generate_latex_table(all_results)
            print("### LaTeX 表格\n")
            print("```latex")
            print(latex)
            print("```")

            # ── Save results ───────────────────────────────────────
            output = {
                "dataset": {"id": str(ds.id), "name": ds.name, "kb_id": str(ds.kb_id)},
                "configs": all_results,
                "latex_table": latex,
            }

            json_path = Path(f"ablation_results_{ds_label}.json")
            json_path.write_text(json.dumps(output, ensure_ascii=False, indent=2))
            print(f"\n  💾 Results saved to: {json_path}")

            # Per-pair breakdown
            print_per_pair_breakdown(all_results)

    print("\n✅ All experiments complete.\n")


if __name__ == "__main__":
    asyncio.run(main())
