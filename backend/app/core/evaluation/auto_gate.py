"""自动化 RAG 质量门禁（Phase 1: Retrieval Quality Gate）。

定位：用户自建知识库的自动化体检 / 回归测试。不要求用户提供人工 GT——
复用「Chunk → 自动出题」能力：从随机抽样的 chunk 生成"真实用户问法"的
检索问题，该 chunk 天然是答案所在 → 自动构成 GT → 跑生产检索链路
（Query Standardization → Dense+BM25 → RRF → Rerank）→ 算 Doc Hit /
Context Recall / MRR / NDCG → 多轮随机采样求均值 + 标准差 → PASS/WARN/FAIL
+ 诊断建议。

与现有人工 GT 门禁（QualityGateService.run_gate）并存：
  - run_gate      → 读固定 EvalDataset 的人工/固定 GT，不采样。
  - run_check     → 每次随机采样 + 自动出题 + 自动 GT，落库可回溯。
两者互不破坏。

设计要点（对应需求）：
  - GT 绑定稳定身份：source_document_hash / chunk_content_hash（重索引后
    通过 content hash 找回，避免 Chunk ID 失效）。
  - 评估数据落库：每次运行建 EvalDataset + EvalQAPair，可回答"这个 92% 是
    哪次采样测的"。
  - 去同源化出题（AutoQuestionGenerator）：问题用学习者问法、避原文术语，
    避免"检索与语料自洽"导致的指标虚高。
  - 多轮采样：每轮随机抽不同文档，汇总均值/标准差/最低/最高轮。
  - 三档判定 + 硬门槛：Doc Hit / Context Recall 低于硬线直接 FAIL，
    防止高分项平均掉严重问题。
"""
from __future__ import annotations

import hashlib
import statistics
import time
import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.evaluation.auto_question_generator import AutoQuestionGenerator
from app.core.evaluation.metrics import (
    chunk_recall_at_k,
    doc_hit_at_k,
    doc_mrr,
    ndcg_at_k,
)
from app.embedding.runtime_config import get_runtime_embedding_config
from app.core.rag.pipeline import RAGPipeline
from app.models.document import Document, DocumentChunk
from app.models.feedback import EvalDataset, EvalQAPair
from app.models.user import User
from app.services.kb_service import KBService

# ── 默认采样与阈值 ────────────────────────────────────────────────
DEFAULT_ROUNDS = 3
DEFAULT_CHUNKS_PER_DOC = 3
DEFAULT_QUESTIONS_PER_CHUNK = 2
EVAL_TOP_K = 5

# Retrieval-only 权重（Phase 1，归一化自用户公式去掉 Faithfulness/OOD）
WEIGHTS = {
    "doc_hit": 0.40,
    "context_recall": 0.35,
    "mrr": 0.125,
    "ndcg": 0.125,
}

PASS_THRESHOLD = 0.85
WARN_THRESHOLD = 0.70
HARD_DOC_HIT = 0.60
HARD_CONTEXT_RECALL = 0.50

DATASET_NAME_PREFIX = "Auto Quality Check"


def _chunk_hash(content: str) -> str:
    """sha256(chunk.content) — 跨重索引的稳定 chunk 锚点。"""
    return hashlib.sha256((content or "").strip().encode("utf-8")).hexdigest()


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


class AutoQualityGate:
    """Automated per-KB RAG retrieval quality gate."""

    @staticmethod
    async def run_check(
        db: AsyncSession,
        kb_id,
        *,
        rounds: int = DEFAULT_ROUNDS,
        chunks_per_doc: int = DEFAULT_CHUNKS_PER_DOC,
        questions_per_chunk: int = DEFAULT_QUESTIONS_PER_CHUNK,
        pipeline: RAGPipeline | None = None,
    ) -> dict:
        """Run an automated quality check over randomly sampled chunks."""
        start = time.monotonic()
        kb = await KBService._get_kb_or_404(db, kb_id)
        uid = str(kb.id)

        # created_by 用系统 admin（评估数据是系统级资源）
        admin = (await db.execute(
            select(User).where(User.role == "admin").order_by(User.created_at).limit(1)
        )).scalars().first()
        if not admin:
            admin = (await db.execute(select(User).order_by(User.created_at).limit(1))).scalars().first()

        pipeline = pipeline or RAGPipeline()

        # ── 1. 随机抽样 rounds 篇文档 ─────────────────────────────
        sampled_doc_ids = (await db.execute(
            select(Document.id)
            .where(Document.kb_id == kb.id)
            .order_by(func.random())
            .limit(max(1, min(rounds, 20)))
        )).scalars().all()

        if not sampled_doc_ids:
            return {
                "kb_id": uid, "status": "no_data",
                "reason": "知识库没有可评估的文档", "suggestions": [],
                "latency_ms": int((time.monotonic() - start) * 1000),
            }

        all_pairs: list[dict] = []

        # ── 2. 逐文档采样 chunk → 出题 → 检索 → 指标 ──────────────
        for r_i, doc_id in enumerate(sampled_doc_ids, 1):
            doc = (await db.execute(select(Document).where(Document.id == doc_id))).scalar_one()
            chunks = (await db.execute(
                select(DocumentChunk)
                .where(DocumentChunk.doc_id == doc_id)
                .order_by(func.random())
                .limit(max(1, min(chunks_per_doc, 10)))
            )).scalars().all()

            for chunk in chunks:
                questions = await AutoQuestionGenerator.generate(
                    chunk_content=chunk.content,
                    doc_title=doc.title or "",
                    count=questions_per_chunk,
                )
                for q in questions:
                    question = q.get("question", "").strip()
                    if not question:
                        continue

                    result = await pipeline.search_for_eval(question, uid, k=EVAL_TOP_K)
                    retrieved = result.get("results", [])
                    retrieved_docs = [str((r.get("metadata") or {}).get("doc_id", "")) for r in retrieved]
                    retrieved_chunks = [str(r.get("chunk_id", "")) for r in retrieved]
                    gt_docs = [str(doc.id)]
                    gt_chunks = [str(chunk.id)]

                    all_pairs.append({
                        "round": r_i,
                        "question": question,
                        "question_type": q.get("type", "concept"),
                        "difficulty": q.get("difficulty", "medium"),
                        "doc_id": str(doc.id),
                        "doc_title": doc.title or "",
                        "chunk_id": str(chunk.id),
                        "chunk_hash": _chunk_hash(chunk.content),
                        "doc_hit": doc_hit_at_k(retrieved_docs, gt_docs, EVAL_TOP_K),
                        "doc_mrr": doc_mrr(retrieved_docs, gt_docs),
                        "ndcg": ndcg_at_k(retrieved_docs, gt_docs, EVAL_TOP_K),
                        "context_recall": chunk_recall_at_k(retrieved_chunks, gt_chunks, EVAL_TOP_K),
                    })

        if not all_pairs:
            return {
                "kb_id": uid, "status": "no_data",
                "reason": "出题失败或没有有效 chunk", "suggestions": [],
                "latency_ms": int((time.monotonic() - start) * 1000),
            }

        # ── 3. 落库（可回溯）──────────────────────────────────────
        dataset = EvalDataset(
            id=uuid.uuid4(),
            name=f"{DATASET_NAME_PREFIX} {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            description="自动化质量门禁采样评估（Phase 1 Retrieval）",
            kb_id=kb.id,
            created_by=admin.id if admin else None,
        )
        db.add(dataset)
        await db.flush()

        for p in all_pairs:
            pair = EvalQAPair(
                id=uuid.uuid4(),
                dataset_id=dataset.id,
                question=p["question"],
                relevant_doc_ids=[p["doc_id"]],
                relevant_doc_titles=[p["doc_title"]],
                ground_truth_chunk_ids=[p["chunk_id"]],
                ground_truth_chunk_id_type="vector_id",
                source_document_id=p["doc_id"],
                source_chunk_id=p["chunk_id"],
                chunk_content_hash=p["chunk_hash"],
                question_type=p["question_type"],
                difficulty=p["difficulty"],
                tags=["auto-gate", f"round-{p['round']}"],
                eval_metadata={
                    "round": p["round"],
                    "top_k": EVAL_TOP_K,
                    "rerank_enabled": settings.rerank_enabled,
                },
            )
            db.add(pair)
        await db.flush()

        # ── 4. 汇总：逐轮 + 全局均值/标准差 ──────────────────────
        round_summaries: list[dict] = []
        for r in sorted({p["round"] for p in all_pairs}):
            rp = [p for p in all_pairs if p["round"] == r]
            round_summaries.append({
                "round": r,
                "n": len(rp),
                "avg_doc_hit": _mean([p["doc_hit"] for p in rp]),
                "avg_context_recall": _mean([p["context_recall"] for p in rp]),
                "avg_mrr": _mean([p["doc_mrr"] for p in rp]),
                "avg_ndcg": _mean([p["ndcg"] for p in rp]),
            })

        avg = {
            "doc_hit": _mean([p["doc_hit"] for p in all_pairs]),
            "context_recall": _mean([p["context_recall"] for p in all_pairs]),
            "mrr": _mean([p["doc_mrr"] for p in all_pairs]),
            "ndcg": _mean([p["ndcg"] for p in all_pairs]),
        }

        def _std(key: str) -> float:
            vals = [p[key] for p in all_pairs]
            return round(statistics.pstdev(vals), 4) if len(vals) >= 2 else 0.0

        std = {
            "doc_hit": _std("doc_hit"),
            "context_recall": _std("context_recall"),
            "mrr": _std("doc_mrr"),
            "ndcg": _std("ndcg"),
        }

        # ── 5. 质量分 + 三档判定 + 硬门槛 ─────────────────────────
        quality_score = round(
            WEIGHTS["doc_hit"] * avg["doc_hit"]
            + WEIGHTS["context_recall"] * avg["context_recall"]
            + WEIGHTS["mrr"] * avg["mrr"]
            + WEIGHTS["ndcg"] * avg["ndcg"],
            4,
        )

        if avg["doc_hit"] < HARD_DOC_HIT or avg["context_recall"] < HARD_CONTEXT_RECALL:
            status = "FAIL"
        elif quality_score >= PASS_THRESHOLD:
            status = "PASS"
        elif quality_score >= WARN_THRESHOLD:
            status = "WARN"
        else:
            status = "FAIL"

        # ── 6. 自动化诊断建议 ────────────────────────────────────
        suggestions = []
        if avg["doc_hit"] >= 0.9:
            suggestions.append("Doc Hit 高：文档定位正常，检索/重排链路健康。")
        elif avg["doc_hit"] >= 0.7:
            suggestions.append("Doc Hit 中：检查 Query Standardization、RRF 权重、BM25 分词与候选数。")
        else:
            suggestions.append("Doc Hit 低：优先确认 Embedding 匹配生产模型、文档已正确入库、候选数足够。")
        if avg["doc_hit"] >= HARD_DOC_HIT and avg["context_recall"] < 0.6:
            suggestions.append("文档命中但答案 chunk 排名差：检查 Chunk 切分质量、导航/模板污染、同文档多 chunk 冗余。")
        if avg["mrr"] < 0.7 and avg["doc_hit"] >= 0.9:
            suggestions.append("正确文档排名靠后（MRR 低）：可关注候选召回与重排顺序，但 Doc Hit 已高，不宜优先更换 Reranker。")

        # 记录实际生效的运行时 embedding 配置（admin 在 UI 设置），而非静态默认值
        _runtime_emb = get_runtime_embedding_config()
        eval_meta = {
            "evaluation_id": str(uuid.uuid4()),
            "dataset_id": str(dataset.id),
            "kb_id": uid,
            "embedding_provider": _runtime_emb.get("provider") or settings.default_embedding_provider,
            "embedding_model": _runtime_emb.get("model") or settings.embedding_model,
            "reranker_model": settings.rerank_model,
            "rerank_enabled": settings.rerank_enabled,
            "candidate_k": max(EVAL_TOP_K * 3, settings.rerank_candidate_k),
            "top_k": EVAL_TOP_K,
            "rrf_alpha": 0.6,
            "chunking_version": "current",
            "cleaning_version": "current",
            "evaluation_timestamp": datetime.now().isoformat(),
        }

        # 持久化到 KB（供质量报告页展示；mode 标记来源为自动门禁）
        kb.quality_status = status
        kb.quality_metrics_json = {
            "mode": "auto",
            "status": status,
            "quality_score": quality_score,
            "total_qa": len(all_pairs),
            "rounds": len(round_summaries),
            "metrics": {
                "avg_doc_hit_at_5": avg["doc_hit"],
                "avg_chunk_recall_at_5": avg["context_recall"],
                "avg_doc_mrr": avg["mrr"],
                "avg_ndcg_at_5": avg["ndcg"],
            },
            "run_at": datetime.now().isoformat(),
            "eval_meta": eval_meta,
        }
        await db.flush()

        return {
            "kb_id": uid,
            "status": status,
            "quality_score": quality_score,
            "total_qa": len(all_pairs),
            "rounds": len(round_summaries),
            "avg_metrics": avg,
            "std_metrics": std,
            "per_round": round_summaries,
            "thresholds": {
                "pass": PASS_THRESHOLD,
                "warn": WARN_THRESHOLD,
                "hard_doc_hit": HARD_DOC_HIT,
                "hard_context_recall": HARD_CONTEXT_RECALL,
                "weights": WEIGHTS,
            },
            "suggestions": suggestions,
            "eval_meta": eval_meta,
            "per_pair": all_pairs,
            "latency_ms": int((time.monotonic() - start) * 1000),
        }
