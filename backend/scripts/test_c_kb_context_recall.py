#!/usr/bin/env python3
"""为个人 C 语言知识库标注考题并测试上下文召回率。

流程:
  1. 清理库内残留旧文档
  2. 创建评估数据集（绑定"我的C语言笔记"）
  3. 添加 5 道代表性考题，GT 文档手动指定、GT chunk 用 embedding 语义匹配自动标注
  4. admin 跑质量门禁 → doc_hit@5 + context_recall@5
"""
from __future__ import annotations

import asyncio
import json
import math
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.db.session import async_session_factory
from app.embedding.factory import get_embedding_model
from app.models.document import DocumentChunk

BASE = f"http://localhost:{sys.argv[1] if len(sys.argv) > 1 else '8085'}/api/v1"

# (问题, 目标文档 title, 说明)
QUESTIONS = [
    ("C语言中如何声明和使用指针？指针变量的声明语法是什么？", "c_pointers.html", "指针声明与使用"),
    ("C语言中指针和数组有什么关系？如何通过指针访问数组元素？", "c_pointers.html", "指针与数组"),
    ("C语言函数如何定义和调用？函数参数是如何传递的？", "c_functions.html", "函数定义与调用"),
    ("C语言结构体（struct）如何定义和使用？", "c_structs.html", "结构体"),
    ("C语言中字符串如何存储？常用的字符串操作函数有哪些？", "c_strings.html", "字符串"),
]


def api(method: str, path: str, token: str = "", body: dict | None = None):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8") if body else None,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"} if (token or body) else {},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode("utf-8"))


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb + 1e-9)


async def find_gt_chunk(emb, doc_id: str, question: str) -> str:
    """在目标文档的 chunks 里语义匹配最相关的 chunk id。"""
    async with async_session_factory() as db:
        chunks = (await db.execute(
            select(DocumentChunk).where(DocumentChunk.doc_id == doc_id)
        )).scalars().all()
    qv = await emb.embed_text(question)
    best, best_score = None, -1
    for c in chunks:
        cv = await emb.embed_text(c.content[:1500])
        s = cosine(qv, cv)
        if s > best_score:
            best, best_score = c.id, s
    return str(best), best_score


async def main() -> None:
    emb = get_embedding_model()

    # ── 1. 清点文档 ──
    async with async_session_factory() as db:
        from app.models.document import Document
        from app.models.knowledge_base import KnowledgeBase
        kb = (await db.execute(
            select(KnowledgeBase).where(KnowledgeBase.name == "我的C语言笔记")
        )).scalars().first()
        docs = (await db.execute(
            select(Document).where(Document.kb_id == kb.id).order_by(Document.created_at)
        )).scalars().all()
        doc_by_title: dict[str, tuple[str, list]] = {}
        for d in docs:
            doc_by_title.setdefault(d.title, []).append(d)
        print(f"[1] 库内文档: {len(docs)} 条")

        # 删除旧残留（同 title 保留最新）
        stale = []
        for title, items in doc_by_title.items():
            for d in items[:-1]:
                stale.append(d)
        if stale:
            for d in stale:
                await db.delete(d)
                print(f"    删除残留: {d.title} ({d.id})")
            await db.flush()

    # ── 2/3. 创建数据集 + 标注 ──
    t3 = api("POST", "/auth/login", body={"username": "tester1", "password": "test123456"})["access_token"]
    kb_id = api("GET", "/kbs?pageSize=50", t3)["items"]
    kb_id = next(k["id"] for k in kb_id if k["name"] == "我的C语言笔记")
    ds = api("POST", "/eval/datasets", t3, body={
        "name": "C语言基础问答 v1",
        "description": "个人 C 库检索质量考题（指针/函数/结构体/字符串）",
        "kb_id": kb_id,
    })
    print(f"[2] 数据集: {ds.get('name')} ({ds.get('id')})")

    pairs = []
    async with async_session_factory() as db:
        from app.models.document import Document
        latest = {}
        for d in (await db.execute(
            select(Document).where(Document.kb_id == kb_id).order_by(Document.created_at.desc())
        )).scalars().all():
            latest.setdefault(d.title, d)

    for question, doc_title, note in QUESTIONS:
        doc = latest[doc_title]
        chunk_id, score = await find_gt_chunk(emb, str(doc.id), question)
        pairs.append({
            "question": question,
            "reference_answer": f"参考: {doc_title} 中关于 {note} 的内容",
            "relevant_doc_ids": [str(doc.id)],
            "ground_truth_chunk_ids": [chunk_id],
            "ground_truth_chunk_id_type": "vector_id",
            "ground_truth_notes": f"[自动标注] {doc_title} - {note} (sim={score:.3f})",
        })
        print(f"    标注: {question[:30]}... → {doc_title} (sim={score:.3f})")

    resp = api("POST", f"/eval/datasets/{ds['id']}/qa-pairs", t3, body=pairs)
    print(f"[3] 已添加 {len(resp)} 道考题")

    # ── 4. 跑门禁 ──
    admin = api("POST", "/auth/login", body={"username": "admin", "password": "admin123"})["access_token"]
    print("[4] 运行质量门禁...")
    r = api("POST", f"/kbs/{kb_id}/quality-gate", admin)
    print()
    print("=== 门禁结果 ===")
    print("status:", r.get("status"))
    print("total_qa:", r.get("total_qa"), "| doc_level:", r.get("doc_level_pairs"), "| chunk_level:", r.get("chunk_level_pairs"))
    m = r.get("metrics", {})
    print(f"doc_hit@5:      {m.get('avg_doc_hit_at_5')}  (门槛 {r.get('thresholds',{}).get('doc_hit_at_5')})")
    print(f"context_recall: {m.get('avg_chunk_recall_at_5')}  (门槛 {r.get('thresholds',{}).get('chunk_recall_at_5')})")
    print(f"MRR: {m.get('avg_doc_mrr')} | NDCG: {m.get('avg_ndcg_at_5')}")
    print()
    print("逐题明细:")
    for p in r.get("per_pair", []):
        print(f"  {p['question'][:28]:<30} doc_hit={p['doc_hit_at_5']} chunk_recall={p['chunk_recall_at_5']}")


if __name__ == "__main__":
    asyncio.run(main())
