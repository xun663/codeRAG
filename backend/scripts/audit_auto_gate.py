"""审计自动体检的逐题命中——重跑检索核对 GT，输出失败详情。

自动体检只把题目+GT 落库，没存逐题检索结果。本脚本对某 KB 最近一次
"Auto Quality Check" 数据集的每题重新跑检索，算 doc_hit/context_recall，
并打印失败题目的"实际检索到了什么"（帮助定位是分块问题还是内容难检索）。

用法：cd backend && python scripts/audit_auto_gate.py <kb_id> [top_k]
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime

from sqlalchemy import select

from app.db.session import async_session_factory
from app.models.feedback import EvalDataset, EvalQAPair
from app.models.document import Document


async def _warm_embedding_config(db) -> None:
    from app.core.monitoring.config_manager import ConfigManager, EMBEDDING_CONFIG_KEY
    from app.embedding.factory import clear_embedding_model_cache
    from app.embedding.runtime_config import set_runtime_embedding_config
    from app.llm.crypto import decrypt

    cfg = await ConfigManager.get_config(db, EMBEDDING_CONFIG_KEY)
    if cfg and cfg.config_value:
        v = cfg.config_value
        set_runtime_embedding_config({
            "provider": v.get("provider", "openai"),
            "base_url": v.get("base_url", ""),
            "model": v.get("model", ""),
            "api_key": decrypt(v.get("api_key_encrypted", "")),
            "dimension": int(v.get("dimension") or 1024),
        })
        clear_embedding_model_cache()
        print(f"🌡️  嵌入配置已加载（{v.get('model')}）")


async def audit(kb_id: str, top_k: int = 5) -> None:
    from app.core.rag.pipeline import RAGPipeline
    from app.core.evaluation.metrics import doc_hit_at_k, chunk_recall_at_k

    async with async_session_factory() as db:
        await _warm_embedding_config(db)
        # 找最近一次 Auto Quality Check 数据集
        ds = (await db.execute(
            select(EvalDataset).where(EvalDataset.kb_id == kb_id)
            .order_by(EvalDataset.created_at.desc()).limit(1)
        )).scalars().first()
        if not ds:
            print("❌ 没找到 Auto Quality Check 数据集"); return
        pairs = (await db.execute(
            select(EvalQAPair).where(EvalQAPair.dataset_id == ds.id)
        )).scalars().all()
        print(f"📊 数据集: {ds.name}（{ds.created_at.strftime('%m-%d %H:%M')}） {len(pairs)} 题\n")

    pipeline = RAGPipeline()
    doc_titles = {}
    doc_hit_sum = cr_sum = 0
    fails = []

    async with async_session_factory() as db:
        for p in pairs:
            gt_doc = (p.relevant_doc_ids or [""])[0]
            gt_chunks = p.ground_truth_chunk_ids or []
            result = await pipeline.search_for_eval(p.question, kb_id, k=top_k)
            retrieved = result.get("results", [])
            retrieved_docs = [str((r.get("metadata") or {}).get("doc_id", "")) for r in retrieved]
            retrieved_chunks = [str(r.get("chunk_id", "")) for r in retrieved]

            doc_hit = doc_hit_at_k(retrieved_docs, [gt_doc], top_k)
            cr = chunk_recall_at_k(retrieved_chunks, gt_chunks, top_k)
            doc_hit_sum += doc_hit
            cr_sum += cr

            if gt_doc not in doc_titles:
                d = (await db.execute(select(Document).where(Document.id == gt_doc))).scalars().first()
                doc_titles[gt_doc] = d.title if d else "?"

            if doc_hit == 0 or cr == 0:
                top_docs = [str((r.get("metadata") or {}).get("doc_id", "")) for r in retrieved[:3]]
                titles = []
                for did in top_docs:
                    if did not in doc_titles:
                        d = (await db.execute(select(Document).where(Document.id == did))).scalars().first()
                        doc_titles[did] = d.title if d else "?"
                    titles.append(doc_titles[did])
                fails.append({
                    "q": p.question, "type": p.question_type, "diff": p.difficulty,
                    "gt_doc": doc_titles[gt_doc], "doc_hit": doc_hit, "cr": cr,
                    "got_titles": titles,
                    "got_previews": [r.get("content_preview", "")[:60] for r in retrieved[:3]],
                })

    n = len(pairs)
    print(f"✅ doc_hit={round(doc_hit_sum/n,3)}  context_recall={round(cr_sum/n,3)}  ({n} 题)\n")
    print(f"=== 失败 {len(fails)} 题 ===")
    for f in fails:
        print(f"❌ [{f['type']}/{f['diff']}] doc_hit={f['doc_hit']} cr={f['cr']}")
        print(f"   答案应在: {f['gt_doc']}")
        print(f"   实际检索到: {f['got_titles']}")
        print(f"   Q: {f['q'][:75]}")
        for prev in f["got_previews"]:
            print(f"     ↳ {prev}")
        print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("用法: python scripts/audit_auto_gate.py <kb_id> [top_k]")
    top_k = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    asyncio.run(audit(sys.argv[1], top_k))
