"""GT 人工标注辅助工具 — 让人来标，而不是关键词自动标。

用法（服务器 / 本地，CWD=backend）：
  1) 看文档和 chunk（人读着判断"答案在哪段"）：
     /home/coderag/venv/bin/python /opt/coderag/deploy/gt_annotate_helper.py dump <kb_id>
  2) 把标注写进 annotations.json（格式见下方模板）
  3) 入库（会清掉该 KB 的旧 eval_dataset，保证门禁只看到这份人工 GT）：
     /home/coderag/venv/bin/python /opt/coderag/deploy/gt_annotate_helper.py import <kb_id> annotations.json

标注模板 annotations.json：
[
  {
    "question": "Python 中列表和元组的主要区别是什么？",
    "doc": "datastructures",
    "chunk_indices": [3, 4],
    "reference_answer": "列表可变，元组不可变；元组由逗号分隔的元素组成。",
    "difficulty": "easy"
  }
]

字段说明：
  question        评估问题
  doc             文档标题子串（dump 输出里那个 .md 名）
  chunk_indices   dump 输出里该文档下的 [索引]（0 起），只标答案实际落到的 1-3 个
  reference_answer 参考回答（可写可不写，建议写便于人工核对）
  difficulty      easy / medium / hard
"""
from __future__ import annotations

import asyncio
import json
import sys
import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session_factory
from app.models.document import Document, DocumentChunk
from app.models.feedback import EvalDataset, EvalQAPair
from app.models.knowledge_base import KnowledgeBase
from app.models.user import User

DATASET_NAME = "Python GT 人工标注"


async def _resolve_kb(db: AsyncSession, kb_id: str) -> KnowledgeBase:
    kb = (await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb_id))).scalar_one_or_none()
    if not kb:
        # 找不到就用名字/文档数兜底
        kbs = (await db.execute(select(KnowledgeBase).order_by(KnowledgeBase.created_at))).scalars().all()
        for k in kbs:
            if kb_id.lower() in k.name.lower():
                return k
        raise SystemExit(f"❌ 找不到知识库 {kb_id}，可用: {[k.name for k in kbs]}")
    return kb


async def dump(db: AsyncSession, kb: KnowledgeBase, doc_filter: str | None = None) -> None:
    """打印 KB 的文档和每个 chunk（索引 + 预览），人看着挑。支持按文档名过滤。"""
    q = select(Document).where(Document.kb_id == kb.id)
    if doc_filter:
        q = q.where(Document.title.like(f"%{doc_filter}%"))
    docs = (await db.execute(q.order_by(Document.title))).scalars().all()
    print(f"📚 知识库: {kb.name}（{len(docs)} 篇文档）\n")
    for doc in docs:
        chunks = (await db.execute(
            select(DocumentChunk).where(DocumentChunk.doc_id == doc.id).order_by(DocumentChunk.chunk_index)
        )).scalars().all()
        print(f"📄 {doc.title}  (chunk 数: {len(chunks)})")
        for c in chunks:
            preview = c.content[:70].replace("\n", " ")
            print(f"   [{c.chunk_index}] {preview}")
        print()


async def import_annotations(db: AsyncSession, kb: KnowledgeBase, annotations: list[dict]) -> None:
    """读人工标注，清掉旧数据集，重建一份干净的人工 GT。"""
    # 清掉该 KB 的全部旧 eval_dataset（含自动 GT），保证门禁只看人工标注
    old = (await db.execute(select(EvalDataset).where(EvalDataset.kb_id == kb.id))).scalars().all()
    for ds in old:
        await db.execute(delete(EvalQAPair).where(EvalQAPair.dataset_id == ds.id))
        await db.delete(ds)
    await db.flush()
    print(f"♻️  已清除 {len(old)} 个旧数据集（含自动 GT）")

    user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    ds = EvalDataset(id=uuid.uuid4(), name=DATASET_NAME,
                     description="人工语义标注 GT", kb_id=kb.id, created_by=user.id)
    db.add(ds)
    await db.flush()

    inserted = 0
    for a in annotations:
        # 解析文档
        r = await db.execute(select(Document).where(
            Document.kb_id == kb.id, Document.title.like(f"%{a['doc']}%")
        ))
        doc = r.scalars().first()
        if not doc:
            print(f"  ⚠️ 未找到文档 '{a['doc']}'，跳过: {a['question'][:30]}")
            continue
        # 解析 chunk（按 chunk_index）
        r2 = await db.execute(select(DocumentChunk).where(
            DocumentChunk.doc_id == doc.id,
            DocumentChunk.chunk_index.in_(a["chunk_indices"]),
        ).order_by(DocumentChunk.chunk_index))
        chunks = r2.scalars().all()
        if not chunks:
            print(f"  ⚠️ 文档 '{doc.title}' 里找不到 chunk {a['chunk_indices']}，跳过")
            continue
        db.add(EvalQAPair(
            id=uuid.uuid4(), dataset_id=ds.id,
            question=a["question"], reference_answer=a.get("reference_answer"),
            relevant_doc_ids=[str(doc.id)], relevant_doc_titles=[doc.title],
            ground_truth_chunk_ids=[str(c.id) for c in chunks],
            ground_truth_chunk_id_type="vector_id",
            difficulty=a.get("difficulty", "medium"), tags=["Python", "人工GT"],
        ))
        print(f"  ✅ [{a.get('difficulty','medium')}] {a['question'][:35]} → {doc.title} chunks{a['chunk_indices']}")
        inserted += 1

    await db.commit()
    print(f"\n✅ 已入库 {inserted} 条人工 GT（数据集: {DATASET_NAME}）")
    print(f"   下一步跑门禁（gate 模式）: python gt_annotate_helper.py gate {kb.id}")


async def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(1)
    mode, kb_id = sys.argv[1], sys.argv[2]
    async with async_session_factory() as db:
        kb = await _resolve_kb(db, kb_id)
        if mode == "dump":
            await dump(db, kb, sys.argv[3] if len(sys.argv) > 3 else None)
        elif mode == "import":
            if len(sys.argv) < 4:
                raise SystemExit("❌ import 模式需要标注文件路径: import <kb_id> annotations.json")
            with open(sys.argv[3], "r", encoding="utf-8") as f:
                annotations = json.load(f)
            await import_annotations(db, kb, annotations)
        elif mode == "gate":
            # 预热嵌入运行时配置（独立进程无 lifespan）
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
            from app.core.evaluation.gate import QualityGateService
            print("\n🔍 运行质量门禁（对当前人工 GT）...")
            report = await QualityGateService.run_gate(db, kb.id)
            await db.commit()
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            raise SystemExit(f"❌ 未知模式: {mode}（支持 dump / import / gate）")


if __name__ == "__main__":
    asyncio.run(main())
