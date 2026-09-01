#!/usr/bin/env python3
"""精选 C 语言资料测试：30 页明确内容 → 个人库 → 10 道考题 → 门禁。

背景: 之前 4 页小库 top-5 ≈ 全库，context_recall 100% 虚高无区分度。
本次挑选 30 个主题明确的教程页（排除练习/生活实例/碎片页），
语料 ~30-40 chunks 后 top-5 只占 ~15%，doc_hit/context_recall 恢复区分度。

用法: python test_c_kb_selected.py [port]
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
from app.models.document import Document, DocumentChunk
from app.models.knowledge_base import KnowledgeBase

BASE = f"http://localhost:{sys.argv[1] if len(sys.argv) > 1 else '8085'}/api/v1"
DESKTOP_C = Path(r"C:\Users\xun\Desktop\C语言资料\w3schools")

KB_NAME = "C语言精选测试"

# ── 30 个主题明确的教程页 ──
SELECTED_PAGES = [
    "c_syntax", "c_variables", "c_data_types", "c_constants", "c_operators",
    "c_conditions", "c_switch", "c_while_loop", "c_for_loop", "c_break_continue",
    "c_arrays", "c_strings", "c_user_input", "c_structs", "c_enums",
    "c_typedef", "c_unions", "c_memory_address", "c_pointers", "c_pointers_arrays",
    "c_pointer_to_pointer", "c_functions", "c_functions_parameters", "c_functions_recursion",
    "c_scope", "c_math", "c_files", "c_files_read", "c_files_write", "c_memory_management",
]

# ── 10 道考题（每题对应一个明确页面）──
QUESTIONS = [
    ("C语言中变量如何声明和初始化？有哪些基本变量类型？", "c_variables"),
    ("C语言的数据类型有哪些？各自的取值范围和大小是多少？", "c_data_types"),
    ("C语言的 if-else 条件语句如何使用？else if 链怎么写？", "c_conditions"),
    ("C语言 switch 语句的语法是什么？break 语句的作用？", "c_switch"),
    ("C语言数组如何声明和访问元素？数组索引从几开始？", "c_arrays"),
    ("C语言中结构体（struct）如何定义和使用？如何访问成员？", "c_structs"),
    ("C语言中 typedef 的用途是什么？如何给类型起别名？", "c_typedef"),
    ("C语言中二级指针（pointer to pointer）是什么？有什么用？", "c_pointer_to_pointer"),
    ("C语言中文件如何打开和读取？fopen/fgets/fclose 怎么用？", "c_files_read"),
    ("C语言中动态内存分配函数 malloc 如何使用？如何释放内存？", "c_memory_management"),
]


def api(method: str, path: str, token: str = "", body: dict | None = None,
        files: list[tuple[str, Path]] | None = None):
    url = BASE + path
    data = None
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif files:
        boundary = "----coderag" + str(int(time.time()))
        parts = []
        for name, fp in files:
            parts.append(f"--{boundary}\r\n".encode())
            parts.append(f'Content-Disposition: form-data; name="file"; filename="{fp.name}"\r\n'.encode())
            parts.append(b"Content-Type: text/html\r\n\r\n")
            parts.append(fp.read_bytes())
            parts.append(b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        data = b"".join(parts)
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        return e.code, json.loads(raw) if raw.strip() else {}


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb + 1e-9)


async def find_gt_chunk(emb, doc_id: str, question: str) -> tuple[str, float]:
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

    # ── 1. 建库 + 上传 30 页 ──
    _, login_r = api("POST", "/auth/login", body={"username": "tester1", "password": "test123456"})
    t3 = login_r["access_token"]
    _, kbs_r = api("GET", "/kbs?pageSize=50", t3)
    existing = kbs_r["items"]
    kb_id = next((k["id"] for k in existing if k["name"] == KB_NAME), None)
    if kb_id:
        api("DELETE", f"/kbs/{kb_id}", t3)
        print(f"[1] 删除旧库 {KB_NAME}")
    _, kb = api("POST", "/kbs", t3, body={
        "name": KB_NAME,
        "description": "精选 30 页主题明确的 C 教程（检索质量测试）",
        "kb_type": "c",
    })
    kb_id = kb["id"]
    print(f"[1] 创建库 {KB_NAME} ({kb_id[:8]})")

    print(f"[2] 上传 {len(SELECTED_PAGES)} 个页面:")
    ok = fail = 0
    for name in SELECTED_PAGES:
        fp = DESKTOP_C / f"{name}.html"
        if not fp.exists():
            print(f"    [缺失] {name}.html")
            fail += 1
            continue
        status, resp = api("POST", f"/kbs/{kb_id}/documents/upload", t3, files=[("file", fp)])
        if status == 201 and isinstance(resp, dict) and resp.get("status") == "indexed":
            ok += 1
        else:
            fail += 1
            print(f"    [失败] {name} (HTTP {status})")
    print(f"    上传完成: {ok} 成功, {fail} 失败")

    # ── 2. 等待索引 ──
    print("[3] 等待索引:")
    for attempt in range(40):
        time.sleep(3)
        _, listing = api("GET", f"/kbs/{kb_id}/documents?pageSize=100", t3)
        docs = listing.get("items", [])
        states = {}
        for d in docs:
            states[d["status"]] = states.get(d["status"], 0) + 1
        if all(d["status"] == "indexed" for d in docs) and len(docs) == len(SELECTED_PAGES):
            print(f"    第 {attempt+1} 轮: {states} ✅")
            break
    _, stats = api("GET", f"/kbs/{kb_id}/stats", t3)
    print(f"    KB 统计: {stats['doc_count']} 文档 / {stats['chunk_count']} chunks / "
          f"平均 {stats['avg_chunk_size']} tokens/chunk")

    # ── 3. 标注 10 道考题 ──
    _, ds = api("POST", "/eval/datasets", t3, body={
        "name": "C语言精选测试 v1",
        "description": "30 页精选库检索质量考题",
        "kb_id": kb_id,
    })
    print(f"[4] 数据集: {ds['id'][:8]}")

    pairs = []
    async with async_session_factory() as db:
        latest = {}
        for d in (await db.execute(
            select(Document).where(Document.kb_id == kb_id).order_by(Document.created_at.desc())
        )).scalars().all():
            latest.setdefault(d.title, d)

    for question, page in QUESTIONS:
        doc = latest.get(f"{page}.html")
        if not doc:
            print(f"    [跳过] 找不到 {page}.html 的文档记录")
            continue
        chunk_id, score = await find_gt_chunk(emb, str(doc.id), question)
        pairs.append({
            "question": question,
            "reference_answer": f"参考: {page}.html 中相关内容",
            "relevant_doc_ids": [str(doc.id)],
            "ground_truth_chunk_ids": [chunk_id],
            "ground_truth_chunk_id_type": "vector_id",
            "ground_truth_notes": f"[自动标注] {page}.html (sim={score:.3f})",
        })
        print(f"    标注: {question[:22]}... → {page}.html (sim={score:.3f})")

    _, resp = api("POST", f"/eval/datasets/{ds['id']}/qa-pairs", t3, body=pairs)
    print(f"[5] 已添加 {len(resp)} 道考题")

    # ── 4. 跑门禁 ──
    _, admin_r = api("POST", "/auth/login", body={"username": "admin", "password": "admin123"})
    admin = admin_r["access_token"]
    print("[6] 运行质量门禁...")
    _, r = api("POST", f"/kbs/{kb_id}/quality-gate", admin)
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
        print(f"  {'✅' if p['doc_hit_at_5'] else '❌'} {p['question'][:26]:<28} doc_hit={p['doc_hit_at_5']} chunk_recall={p['chunk_recall_at_5']}")


if __name__ == "__main__":
    asyncio.run(main())
