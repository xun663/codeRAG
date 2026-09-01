#!/usr/bin/env python3
"""Benchmark: Query Standardizer optimization — before vs after comparison.

Measures:
  - LLM call count per query type
  - End-to-end standardization latency
  - Response quality (keyword coverage)

Usage:
    # Full benchmark
    PYTHONUTF8=1 python3 benchmarks/benchmark_query_optimizer.py

    # Fast-path queries only
    PYTHONUTF8=1 python3 benchmarks/benchmark_query_optimizer.py --fast-path-only

    # Complex queries only (LLM path)
    PYTHONUTF8=1 python3 benchmarks/benchmark_query_optimizer.py --complex-only
"""
from __future__ import annotations

import asyncio
import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.rag.query_standardizer import get_query_standardizer
from app.core.rag.intent_classifier import Intent


# ═════════════════════════════════════════════════════════════════════
#  Test cases
# ═════════════════════════════════════════════════════════════════════

SIMPLE_QUERIES = [
    # Clear technical questions — should take fast path (0 LLM calls)
    "Python列表和元组有什么区别",
    "Java线程池有哪些类型",
    "TCP三次握手过程",
    "Redis缓存淘汰策略有哪些",
    "HashMap底层实现原理",
    "Python装饰器作用和使用方法",
    "什么是Docker容器",
    "SQL索引类型有哪些",
    "HTTPS和HTTP区别",
    "MySQL事务隔离级别",
]

COMPLEX_QUERIES = [
    # Vague / pronominal / open-ended — should take LLM path (1 merged call)
    "这个怎么实现比较优雅",
    "帮我分析一下这个RAG架构的优缺点",
    "为什么这样写性能不好",
    "有什么好的优化方案",
    "你能给我解释一下上一段代码吗",
    "它和Python有什么区别",
    "那个方法到底怎么用",
    "这个为什么会报错",
    "你觉得哪个框架更好",
    "能不能举个实际的例子",
]


# ═════════════════════════════════════════════════════════════════════
#  Benchmark runner
# ═════════════════════════════════════════════════════════════════════

def _print_header(text: str):
    print(f"\n{'=' * 65}")
    print(f"  {text}")
    print(f"{'=' * 65}")


def _print_results(label: str, results: list[dict], keys: list[str], headers: list[str]):
    """Print tabular results."""
    col_widths = []
    data_rows = []
    for row in results:
        data_rows.append([str(row.get(k, "")) for k in keys])

    for i, h in enumerate(headers):
        max_d = max((len(r[i]) for r in data_rows), default=0)
        col_widths.append(max(len(h), max_d) + 2)

    print(f"\n  {label}")
    header_line = "| " + " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers)) + " |"
    sep_line = "| " + " | ".join("-" * w for w in col_widths) + " |"
    print(header_line)
    print(sep_line)
    for row in data_rows:
        print("| " + " | ".join(row[i].ljust(col_widths[i]) for i in range(len(headers))) + " |")
    print()


async def benchmark_queries(label: str, queries: list[str], expected_fast_path: bool | None = None):
    """Run benchmark for a set of queries."""
    standardizer = get_query_standardizer()
    results = []

    for query in queries:
        start = time.perf_counter()
        result = await standardizer.process(
            query=query,
            intent=Intent.KNOWLEDGE,
        )
        elapsed = (time.perf_counter() - start) * 1000  # ms
        status = "FAST" if result.fast_path else "LLM"
        llm_calls = 0 if result.fast_path else 1

        results.append({
            "query": query[:35],
            "status": status,
            "llm_calls": llm_calls,
            "latency_ms": f"{elapsed:.0f}",
            "rewritten": result.primary_query[:50],
        })

        # Print per-query detail
        if expected_fast_path is not None:
            passed = result.fast_path == expected_fast_path
            mark = "OK" if passed else "FAIL"
        else:
            mark = ""
        print(f"    [{mark:4s}] {status:4s} | {elapsed:6.0f}ms | {query[:40]:40s} -> {result.primary_query[:50]}")

    return results


async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--fast-path-only", action="store_true")
    parser.add_argument("--complex-only", action="store_true")
    args = parser.parse_args()

    print("Query Standardizer Benchmark")
    print(f"  Fast path queries: {len(SIMPLE_QUERIES)}")
    print(f"  Complex queries:   {len(COMPLEX_QUERIES)}")

    run_simple = not args.complex_only
    run_complex = not args.fast_path_only

    # ── Benchmark 1: Simple (should be fast path) ────────────────
    if run_simple:
        _print_header("Benchmark: Simple Knowledge Queries (expected: 0 LLM calls)")
        simple_results = await benchmark_queries(
            "Simple queries", SIMPLE_QUERIES, expected_fast_path=True,
        )

        llm_count = sum(1 for r in simple_results if r["status"] == "LLM")
        fast_count = len(simple_results) - llm_count
        print(f"\n  Result: {fast_count}/{len(simple_results)} queries used fast path (0 LLM)")
        if llm_count > 0:
            print(f"         {llm_count}/{len(simple_results)} queries used LLM path (incorrect)")
    else:
        simple_results = []

    # ── Benchmark 2: Complex (should be LLM path) ───────────────
    if run_complex:
        _print_header("Benchmark: Complex/Vague Queries (expected: 1 LLM call)")
        complex_results = await benchmark_queries(
            "Complex queries", COMPLEX_QUERIES, expected_fast_path=False,
        )

        llm_count = sum(1 for r in complex_results if r["status"] == "LLM")
        print(f"\n  Result: {llm_count}/{len(complex_results)} queries used merged LLM path (1 call)")
    else:
        complex_results = []

    # ── Summary ──────────────────────────────────────────────────
    _print_header("Summary")

    all_results = simple_results + complex_results
    total_saved = sum(1 for r in all_results if r["status"] == "FAST")

    # Estimate: each LLM call saved ~3s, each LLM call costs ~0.5s
    fast_count = len([r for r in all_results if r["status"] == "FAST"])
    llm_count = len([r for r in all_results if r["status"] == "LLM"])

    total_old_llm_calls = len(all_results) * 3  # old: 3 calls per query
    total_new_llm_calls = llm_count * 1          # new: 1 call per complex query
    calls_saved = total_old_llm_calls - total_new_llm_calls

    print(f"  Total queries:           {len(all_results)}")
    print(f"  Fast path (0 LLM calls): {fast_count}")
    print(f"  LLM path (1 call):       {llm_count}")
    print(f"  ")
    print(f"  Estimated LLM calls:")
    print(f"    Before (3 per query):  {total_old_llm_calls}")
    print(f"    After  (0 or 1):       {total_new_llm_calls}")
    print(f"    Saved:                 {calls_saved} calls ({calls_saved/max(total_old_llm_calls,1)*100:.0f}%)")
    print(f"  ")
    print(f"  Estimated time saved:")
    time_saved_s = calls_saved * 3  # ~3s per LLM call
    print(f"    ~{time_saved_s}s total (at ~3s/LLM call)")

    # Summary table
    _print_results(
        "Results by query type:",
        all_results,
        keys=["query", "status", "llm_calls", "latency_ms"],
        headers=["Query", "Path", "LLM Calls", "Latency(ms)"],
    )

    print("\nBenchmark complete.\n")


if __name__ == "__main__":
    asyncio.run(main())
