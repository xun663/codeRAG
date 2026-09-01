#!/usr/bin/env python3
"""客观验证 GT 归属：对每个存疑主题，在 KB 所有文档中搜索关键词，
输出每个文档的命中次数，据此判断 GT 标注是否正确。"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.db.session import async_session_factory
from app.models.document import Document, DocumentChunk

# (label, kb_id, [(query, [keywords])])
SCAN = {
    "Python": {
        "kb_id": "126739c2-e665-4e69-ad59-14218fe5c95d",
        "topics": [
            ("列表推导式", ["列表推导式", "list comprehension", "推导式"]),
            ("list vs tuple", ["列表", "元组", "tuple"]),
            ("lambda", ["lambda", "匿名函数"]),
            ("定义函数", ["def ", "函数定义", "定义函数", "def f"]),
            ("pip/venv", ["pip", "venv", "虚拟环境", "pip install"]),
            ("切片", ["切片", "slicing", "序列"]),
        ],
    },
    "Java": {
        "kb_id": "34139461-a995-4f77-86bd-ced21883929d",
        "topics": [
            ("访问修饰符", ["public", "private", "protected", "访问修饰符", "修饰符"]),
            ("final", ["final"]),
            ("== vs equals", ["equals", "==", "字符串比较"]),
            ("autoboxing", ["autoboxing", "自动装箱", "装箱", "wrapper"]),
            ("synchronized", ["synchronized", "同步", "同步机制"]),
        ],
    },
}


async def main():
    async with async_session_factory() as db:
        for label, cfg in SCAN.items():
            kb_id = cfg["kb_id"]
            docs = (
                (await db.execute(select(Document).where(Document.kb_id == kb_id)))
                .scalars()
                .all()
            )
            # 预加载每个 doc 的全部 chunk 文本
            doc_text = {}
            for d in docs:
                chunks = (
                    (await db.execute(
                        select(DocumentChunk.content).where(DocumentChunk.doc_id == d.id)
                    ))
                    .scalars()
                    .all()
                )
                doc_text[str(d.id)] = (d.title, " ".join(chunks))

            print(f"\n{'=' * 78}\n  {label} KB\n{'=' * 78}")
            for topic, kws in cfg["topics"]:
                print(f"\n■ {topic}  关键词: {kws}")
                hits = []
                for doc_id, (title, text) in doc_text.items():
                    cnt = sum(text.lower().count(k.lower()) for k in kws)
                    if cnt > 0:
                        hits.append((cnt, title))
                hits.sort(reverse=True)
                for cnt, title in hits[:5]:
                    print(f"    {cnt:>4} 次  {title}")


if __name__ == "__main__":
    asyncio.run(main())
