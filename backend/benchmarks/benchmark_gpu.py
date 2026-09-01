#!/usr/bin/env python3
"""GPU vs CPU performance benchmark for Embedding & Reranker.

Usage:
    # Full benchmark (embedding + reranker)
    python benchmarks/benchmark_gpu.py

    # Embedding only
    python benchmarks/benchmark_gpu.py --embedding-only

    # Reranker only
    python benchmarks/benchmark_gpu.py --reranker-only

Output is printed as a markdown table suitable for copying into the thesis.

Environment:
    Set ``CUDA_VISIBLE_DEVICES=""`` to force CPU mode for comparison.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import sys
import time
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

# ── Sample data ────────────────────────────────────────────────────────

SAMPLE_CHUNKS_100 = [
    f"Chunk {i}: Python is a high-level, general-purpose programming language. "
    f"Its design philosophy emphasizes code readability with the use of significant indentation. "
    f"Python is dynamically typed and garbage-collected."
    for i in range(100)
]

SAMPLE_CHUNKS_500 = [
    f"Chunk {i}: Java is a high-level, class-based, object-oriented programming language "
    f"that is designed to have as few implementation dependencies as possible. "
    f"It is a general-purpose programming language intended to let application developers write once, run anywhere."
    for i in range(500)
]

SAMPLE_QUERY = "What is the difference between Python and Java?"

SAMPLE_DOCS_FOR_RERANK = [
    {
        "id": f"doc_{i}",
        "document": (
            f"Document {i}: Programming languages provide abstractions for expressing "
            f"computations. Different languages have different design philosophies. "
            f"Python emphasizes readability, Java emphasizes portability. "
        ),
        "metadata": {"doc_title": f"Programming Guide {i // 10}", "kb_id": "test"},
    }
    for i in range(50)
]


# ── Helpers ─────────────────────────────────────────────────────────────

def _try_import_torch():
    """Import torch; return None if unavailable."""
    try:
        import torch
        return torch
    except ImportError:
        return None


def _get_sentence_transformer_model(device: str):
    """Create a fresh SentenceTransformer on the given device."""
    from sentence_transformers import SentenceTransformer
    # Force model path — the model is already cached
    return SentenceTransformer("all-MiniLM-L6-v2", device=device)


def _get_cross_encoder(device: str):
    """Create a fresh CrossEncoder on the given device."""
    from sentence_transformers import CrossEncoder
    return CrossEncoder(
        "cross-encoder/ms-marco-MiniLM-L-6-v2",
        device=device,
        trust_remote_code=True,
    )


def _benchmark_embedding(model, chunks: list[str], label: str) -> dict:
    """Time embedding encode, return stats."""
    import torch

    # Warm up
    _ = model.encode(chunks[:2], batch_size=32, show_progress_bar=False)

    # Synchronise GPU before measuring
    if torch.cuda.is_available():
        torch.cuda.synchronize()

    count = len(chunks)
    t0 = time.perf_counter()
    result = model.encode(chunks, batch_size=32, show_progress_bar=False)
    t1 = time.perf_counter()

    if torch.cuda.is_available():
        torch.cuda.synchronize()
    t2 = time.perf_counter()
    gpu_sync_time = t2 - t1
    elapsed = t1 - t0

    return {
        "label": label,
        "count": count,
        "elapsed_s": round(elapsed, 3),
        "embed_per_sec": round(count / elapsed, 1),
        "gpu_sync_ms": round(gpu_sync_time * 1000, 2),
        "result_shape": f"{len(result)} x {result.shape[1]}",
    }


def _benchmark_reranker(model, query: str, docs: list[dict], label: str) -> dict:
    """Time a single rerank call, return stats."""
    import torch

    pairs = [(query, d["document"]) for d in docs]

    # Warm up
    _ = model.predict(pairs[:2], batch_size=16, show_progress_bar=False)

    if torch.cuda.is_available():
        torch.cuda.synchronize()

    t0 = time.perf_counter()
    scores = model.predict(pairs, batch_size=16, show_progress_bar=False)
    t1 = time.perf_counter()

    if torch.cuda.is_available():
        torch.cuda.synchronize()

    return {
        "label": label,
        "candidate_count": len(docs),
        "elapsed_ms": round((t1 - t0) * 1000, 2),
    }


def _print_heading(text: str):
    print(f"\n{'=' * 60}")
    print(f"  {text}")
    print(f"{'=' * 60}")


def _print_table(rows: list[dict], keys: list[str], headers: list[str]):
    """Print a simple markdown table."""
    # Compute column widths
    col_widths = []
    data_rows = []
    for row in rows:
        data_rows.append([str(row.get(k, "")) for k in keys])

    for i, h in enumerate(headers):
        max_d = max((len(r[i]) for r in data_rows), default=0)
        col_widths.append(max(len(h), max_d) + 2)

    # Header
    header_line = "| " + " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers)) + " |"
    sep_line = "| " + " | ".join("-" * w for w in col_widths) + " |"
    print(header_line)
    print(sep_line)
    for row in data_rows:
        print("| " + " | ".join(row[i].ljust(col_widths[i]) for i in range(len(headers))) + " |")
    print()


# ── Benchmark suites ────────────────────────────────────────────────────

async def benchmark_embedding():
    """Run embedding benchmarks on both devices."""
    _print_heading("Embedding Benchmark")

    # Determine available devices
    import torch
    devices = ["cpu"]
    if torch.cuda.is_available():
        devices.append("cuda")

    results = []

    for device in devices:
        label = f"SentenceTransformer (device={device})"
        print(f"  Loading model on {device}...", end=" ", flush=True)
        model = _get_sentence_transformer_model(device)
        print("done.")

        # 100 chunks
        r = _benchmark_embedding(model, SAMPLE_CHUNKS_100, f"{device} — 100 chunks")
        results.append(r)
        print(f"    {r['count']} chunks: {r['elapsed_s']}s ({r['embed_per_sec']} chunks/s)")

        # 500 chunks
        r = _benchmark_embedding(model, SAMPLE_CHUNKS_500, f"{device} — 500 chunks")
        results.append(r)
        print(f"    {r['count']} chunks: {r['elapsed_s']}s ({r['embed_per_sec']} chunks/s)")

        # Clean up
        del model

    # Summary table
    print("\n  ── Summary ──")
    _print_table(
        results,
        keys=["label", "count", "elapsed_s", "embed_per_sec"],
        headers=["Device", "Chunks", "Time (s)", "Chunks/s"],
    )

    # Speedup ratio
    if len(devices) == 2:
        cpu_100 = next(r for r in results if "cpu" in r["label"] and r["count"] == 100)
        gpu_100 = next(r for r in results if "cuda" in r["label"] and r["count"] == 100)
        cpu_500 = next(r for r in results if "cpu" in r["label"] and r["count"] == 500)
        gpu_500 = next(r for r in results if "cuda" in r["label"] and r["count"] == 500)

        print(f"  ==> Speedup (100 chunks):  {cpu_100['elapsed_s']/gpu_100['elapsed_s']:.1f}x")
        print(f"  ==> Speedup (500 chunks):  {cpu_500['elapsed_s']/gpu_500['elapsed_s']:.1f}x")
        print()


async def benchmark_reranker():
    """Run reranker benchmarks on both devices."""
    _print_heading("Reranker Benchmark")

    import torch
    devices = ["cpu"]
    if torch.cuda.is_available():
        devices.append("cuda")

    results = []

    for device in devices:
        label = f"CrossEncoder (device={device})"
        print(f"  Loading model on {device}...", end=" ", flush=True)
        model = _get_cross_encoder(device)
        print("done.")

        r = _benchmark_reranker(model, SAMPLE_QUERY, SAMPLE_DOCS_FOR_RERANK, label)
        results.append(r)
        print(f"    {r['candidate_count']} candidates: {r['elapsed_ms']}ms")

        del model

    print("\n  ── Summary ──")
    _print_table(
        results,
        keys=["label", "candidate_count", "elapsed_ms"],
        headers=["Device", "Candidates", "Latency (ms)"],
    )

    if len(devices) == 2:
        cpu = results[0]
        gpu = results[1]
        print(f"  ==> Speedup: {cpu['elapsed_ms']/gpu['elapsed_ms']:.1f}x")
        print()


# ── Entry point ─────────────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(description="GPU vs CPU benchmark")
    parser.add_argument("--embedding-only", action="store_true")
    parser.add_argument("--reranker-only", action="store_true")
    args = parser.parse_args()

    torch = _try_import_torch()
    if torch is None:
        print("❌ torch not installed. Cannot run benchmarks.")
        sys.exit(1)

    print(f"PyTorch version: {torch.__version__}")
    print(f"CUDA available:  {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"GPU device:      {torch.cuda.get_device_name(0)}")
        total_mb = torch.cuda.get_device_properties(0).total_memory / 1024 / 1024
        print(f"VRAM total:      {total_mb:.0f} MB")
    print()

    run_embedding = not args.reranker_only
    run_reranker = not args.embedding_only

    if run_embedding:
        asyncio.run(benchmark_embedding())

    if run_reranker:
        asyncio.run(benchmark_reranker())

    print("Benchmark complete.\n")


if __name__ == "__main__":
    main()
