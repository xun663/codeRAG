#!/usr/bin/env python3
"""普通用户上传测试：C 语言资料 → 个人知识库（完整链路验证，v2）。

模拟真实用户流程:
  1. 登录 tester1（普通用户）
  2. 创建个人知识库（若已存在则复用并清空文档）
  3. 上传桌面的 W3Schools C 教程原始 HTML（不预清洗）
  4. 轮询文档索引状态，输出清洗统计 + chunk 数
  5. 用该库发一条 RAG 问答
  6. 验证作用域隔离（其他用户看不到该库）
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# 端口从命令行传入（默认 8085）；注意 Windows 孤儿 socket 会导致端口漂移，
# 用 start_all.sh 实际输出端口：python test_user_upload_c.py 8087
BASE = f"http://localhost:{sys.argv[1] if len(sys.argv) > 1 else '8085'}/api/v1"
DESKTOP_C = Path(r"C:\Users\xun\Desktop\C语言资料\w3schools")

UPLOAD_FILES = [
    "c_pointers.html",
    "c_functions.html",
    "c_structs.html",
    "c_strings.html",
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
            parts.append(
                f'Content-Disposition: form-data; name="file"; filename="{fp.name}"\r\n'.encode()
            )
            parts.append(b"Content-Type: text/html\r\n\r\n")
            parts.append(fp.read_bytes())
            parts.append(b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        data = b"".join(parts)
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def login(username: str, password: str) -> str:
    _, r = api("POST", "/auth/login", body={"username": username, "password": password})
    return r["access_token"]


def main() -> None:
    t3 = login("tester1", "test123456")
    print("[1] tester1 登录成功")

    # ── 2. 复用/创建个人知识库并清空 ──
    _, kbs = api("GET", "/kbs?pageSize=50", t3)
    kb_id = next((k["id"] for k in kbs["items"] if k["name"] == "我的C语言笔记"), None)
    if kb_id is None:
        _, kb = api("POST", "/kbs", t3, body={
            "name": "我的C语言笔记",
            "description": "从 W3Schools 收集的 C 教程（原始 HTML 上传测试）",
            "kb_type": "c",
        })
        kb_id = kb["id"]
        print(f"[2] 创建知识库 {kb_id}")
    else:
        # 清空旧文档（重新上传验证新清洗器）
        _, docs = api("GET", f"/kbs/{kb_id}/documents?pageSize=50", t3)
        for d in docs.get("items", []):
            api("DELETE", f"/kbs/{kb_id}/documents/{d['id']}", t3)
        print(f"[2] 复用知识库并清空 {len(docs.get('items', []))} 个旧文档")

    # ── 3. 上传 ──
    print("[3] 上传原始 HTML:")
    for fname in UPLOAD_FILES:
        fp = DESKTOP_C / fname
        status, resp = api("POST", f"/kbs/{kb_id}/documents/upload", t3, files=[("file", fp)])
        doc = resp if isinstance(resp, dict) and "id" in resp else {}
        print(f"    {fname}: HTTP {status} | status={doc.get('status')}")

    # ── 4. 轮询索引 ──
    print("[4] 等待索引完成:")
    docs = []
    for attempt in range(40):
        time.sleep(3)
        _, listing = api("GET", f"/kbs/{kb_id}/documents?pageSize=50", t3)
        docs = listing.get("items", [])
        states = {}
        for d in docs:
            states[d["status"]] = states.get(d["status"], 0) + 1
        print(f"    第 {attempt+1} 轮: {states}")
        if all(d["status"] == "indexed" for d in docs):
            break

    # ── 5. 清洗 + chunk 统计 ──
    print("[5] 清洗统计:")
    total_chunks = 0
    for d in docs:
        cl = (d.get("metadata_json") or {}).get("cleaning") or {}
        total_chunks += d.get("chunk_count") or 0
        if cl.get("enabled"):
            print(f"    {d['title'][:45]}: 移除 {cl['removed_pct']}% | {d.get('chunk_count')} chunks")
        else:
            print(f"    {d['title'][:45]}: 无清洗 | {d.get('chunk_count')} chunks")
    _, stats = api("GET", f"/kbs/{kb_id}/stats", t3)
    print(f"    KB 合计: {stats['doc_count']} 文档 / {stats['chunk_count']} chunks / "
          f"平均 {stats['avg_chunk_size']} tokens/chunk")

    # ── 6. RAG 问答 ──
    print("[6] RAG 问答:")
    _, conv = api("POST", "/chat/conversations", t3, body={"kb_id": kb_id, "title": "C语言测试"})
    conv_id = conv["id"]
    _, msg = api("POST", f"/chat/conversations/{conv_id}/messages", t3,
                 body={"content": "C语言中指针是什么？如何声明和使用指针？"})
    answer = msg.get("content", "")
    print(f"    回答前 120 字: {answer[:120].replace(chr(10), ' ')}")
    chunks = msg.get("retrieved_chunks") or []
    print(f"    检索 {len(chunks)} chunks | 来源: {sorted({c.get('doc_title','') for c in chunks})}")

    # ── 7. 隔离验证 ──
    print("[7] 作用域隔离:")
    t2 = login("tester2", "test123456") if True else None
    _, t2_list = api("GET", "/kbs?pageSize=50", t2)
    t2_names = {i["name"] for i in t2_list["items"]}
    print(f"    tester2 视野含该库: {'我的C语言笔记' in t2_names}（应为 False）")

    print("\n=== 完成 ===")


if __name__ == "__main__":
    main()
