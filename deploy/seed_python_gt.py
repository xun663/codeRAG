"""生产环境：为 Python 知识库标注 GT 问答对并运行质量门禁。

用法（服务器上，CWD=backend）：
    cd /opt/coderag/backend && /home/coderag/venv/bin/python /opt/coderag/deploy/seed_python_gt.py

设计：
- 自动定位 Python 知识库（名称含 Python；否则选文档数最多的库）
- GT chunk 按「文档标题子串 + 内容关键词」语义解析，不依赖硬编码 chunk 索引
  （避免生产/本地 chunk 边界不一致导致 GT 失效）
- 建 eval_dataset → 跑门禁 → 打印 doc_hit@5 / context_recall@5 报告
"""
from __future__ import annotations

import asyncio
import json
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session_factory
from app.models.document import Document, DocumentChunk
from app.models.feedback import EvalDataset, EvalQAPair
from app.models.knowledge_base import KnowledgeBase
from app.models.user import User

# ── GT 问答对：question / doc_match(标题子串) / hints(内容关键词) ─────────────
PYTHON_QA: list[dict] = [
    {
        "question": "Python 中列表（list）和元组（tuple）的主要区别是什么？",
        "doc_match": "datastructures",
        "hints": ["元组", "不可变"],
        "reference_answer": "列表可变（可增删改），元组不可变；元组由逗号分隔的元素组成。",
        "difficulty": "easy",
    },
    {
        "question": "Python 的字典（dict）如何创建和访问元素？",
        "doc_match": "datastructures",
        "hints": ["字典", "键"],
        "reference_answer": "用花括号创建字典，键值对存储；通过 d[key] 访问，键必须不可变。",
        "difficulty": "easy",
    },
    {
        "question": "Python 的 for 循环和 while 循环有什么区别？",
        "doc_match": "controlflow",
        "hints": ["for", "while"],
        "reference_answer": "for 遍历可迭代对象，while 在条件为真时循环。",
        "difficulty": "medium",
    },
    {
        "question": "Python 的异常处理 try/except 是如何工作的？",
        "doc_match": "errors",
        "hints": ["异常的处理", "except"],
        "reference_answer": "try 放可能出错的代码，except 捕获并处理异常，finally 执行清理。",
        "difficulty": "medium",
    },
    {
        "question": "Python 中如何打开和读写文件？",
        "doc_match": "inputoutput",
        "hints": ["open", "文件"],
        "reference_answer": "用 open() 打开文件，with 语句自动关闭，'r'/'w'/'a' 指定模式。",
        "difficulty": "medium",
    },
    {
        "question": "Python 中如何定义类和创建对象？__init__ 方法的作用？",
        "doc_match": "classes",
        "hints": ["类定义", "class", "self"],
        "reference_answer": "class 定义类，__init__ 初始化实例属性，self 指向实例。",
        "difficulty": "medium",
    },
    {
        "question": "Python 的模块（module）和 import 语句如何使用？",
        "doc_match": "modules",
        "hints": ["import", "模块"],
        "reference_answer": "import 导入模块，from 导入特定名字；模块是含定义的 .py 文件。",
        "difficulty": "easy",
    },
    {
        "question": "Python 中生成器（generator）和 yield 关键字如何工作？",
        "doc_match": "glossary",
        "hints": ["yield", "生成器"],
        "reference_answer": "yield 返回值并暂停函数，下次调用继续；适合处理大数据流。",
        "difficulty": "hard",
    },
]


async def resolve_kb(db: AsyncSession) -> KnowledgeBase:
    """定位 Python 知识库：名称含 Python，否则选文档最多的库。"""
    kbs = (await db.execute(select(KnowledgeBase).order_by(KnowledgeBase.created_at))).scalars().all()
    if not kbs:
        raise SystemExit("❌ 没有任何知识库")
    for kb in kbs:
        if "python" in kb.name.lower():
            return kb
    # 文档数最多的库
    best = None
    for kb in kbs:
        n = (await db.execute(select(func.count(Document.id)).where(Document.kb_id == kb.id))).scalar_one()
        if best is None or n > best[1]:
            best = (kb, n)
    return best[0]


async def resolve_gt(db: AsyncSession, kb_id, qa: dict):
    """按 标题子串 + 内容关键词 解析 GT chunk。返回 (doc, [chunk_id], [chunk])。"""
    r = await db.execute(
        select(Document).where(Document.kb_id == kb_id, Document.title.like(f"%{qa['doc_match']}%"))
    )
    docs = r.scalars().all()
    if not docs:
        print(f"  ⚠️ 未找到匹配文档 '{qa['doc_match']}'")
        return None, [], []
    doc = docs[0]
    r2 = await db.execute(
        select(DocumentChunk).where(DocumentChunk.doc_id == doc.id).order_by(DocumentChunk.chunk_index)
    )
    chunks = r2.scalars().all()
    scored = [(c, sum(h in c.content for h in qa["hints"])) for c in chunks]
    matched = [c for c, s in scored if s > 0]
    matched.sort(key=lambda c: -sum(h in c.content for h in qa["hints"]))
    selected = matched[:4]  # 最多 4 个 GT chunk
    return doc, [c.id for c in selected], selected


async def main() -> None:
    async with async_session_factory() as db:
        kb = await resolve_kb(db)
        user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
        print(f"📦 知识库: {kb.name} ({kb.id})")

        # 逐条解析 GT，打印预览
        resolved: list[dict] = []
        for qa in PYTHON_QA:
            doc, chunk_ids, chunks = await resolve_gt(db, kb.id, qa)
            if not doc:
                continue
            resolved.append({**qa, "doc_id": doc.id, "chunk_ids": chunk_ids})
            prev = " | ".join(c.content[:40].replace("\n", " ") for c in chunks)
            print(f"  [{qa['difficulty']}] {qa['question'][:30]}... → {doc.title} ({len(chunk_ids)}chunks)")
            if chunks:
                print(f"      ↳ {prev}")

        if not resolved:
            raise SystemExit("❌ 没有成功解析任何 GT 对，请检查 doc_match")

        # 建 eval_dataset + QA pairs（每次重建：GT 关键词可能更新过）
        ds_name = "Python 质量门禁评估"
        from sqlalchemy import delete
        existing = (await db.execute(select(EvalDataset).where(EvalDataset.name == ds_name))).scalar_one_or_none()
        if existing:
            await db.execute(delete(EvalQAPair).where(EvalQAPair.dataset_id == existing.id))
            await db.delete(existing)
            await db.flush()
            print("♻️  重建数据集（GT 关键词已更新）")
        ds = EvalDataset(id=uuid.uuid4(), name=ds_name, description="生产 Python 库语义标注 GT",
                         kb_id=kb.id, created_by=user.id)
        db.add(ds)
        await db.flush()
        for qa in resolved:
            db.add(EvalQAPair(
                id=uuid.uuid4(), dataset_id=ds.id,
                question=qa["question"], reference_answer=qa["reference_answer"],
                relevant_doc_ids=[str(qa["doc_id"])], relevant_doc_titles=[qa["doc_match"]],
                ground_truth_chunk_ids=[str(c) for c in qa["chunk_ids"]] or None,
                ground_truth_chunk_id_type="vector_id",
                difficulty=qa["difficulty"], tags=["Python", "质量门禁"],
            ))
        await db.flush()
        print(f"✅ 数据集 '{ds_name}' 已建，{len(resolved)} 个 GT 对")

        await db.commit()

        # 预热嵌入运行时配置：独立进程没有 uvicorn lifespan，需手动从 DB 加载，
        # 否则回落 .env 的 openai_api_base（DeepSeek）→ 嵌入请求 404
        from app.core.monitoring.config_manager import ConfigManager, EMBEDDING_CONFIG_KEY
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
            from app.embedding.factory import clear_embedding_model_cache
            clear_embedding_model_cache()
            print("🌡️  嵌入运行时配置已加载（dashscope）")

        # 诊断：打印每个问题检索到的 top-5（RRF 基线），对照 GT 看准不准
        from app.core.rag.pipeline import RAGPipeline
        pipeline = RAGPipeline()
        print("\n📋 检索诊断（top-5，RRF 基线，对照用）:")
        for qa in resolved:
            s = await pipeline.search_only(qa["question"], kb_id=str(kb.id), k=5, strategy="hybrid", rerank=False)
            print(f"\n▶ {qa['question'][:28]}")
            for r in s.get("results", []):
                md = r.get("metadata") or {}
                print(f"   [{md.get('doc_title', '?')}] {r.get('content_preview', '')[:45]}")

        # 跑门禁
        from app.core.evaluation.gate import QualityGateService
        print("\n🔍 运行质量门禁（检索级评估，~10-30s）...")
        report = await QualityGateService.run_gate(db, kb.id)
        await db.commit()
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
