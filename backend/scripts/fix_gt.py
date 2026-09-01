#!/usr/bin/env python3
"""修复评估数据集 GT 标注（基于 2026-08-06 rank_audit + 关键词证据）。

Python 数据集 (66be64a4):
  - lambda:          classes.md    → controlflow.md
  - 列表推导式:        introduction.md → datastructures.md
  - pip/venv:        modules.md    → venv.md
  - list/tuple:      introduction.md → datastructures.md
  - 定义函数:          modules.md    → controlflow.md

Java 数据集 (09c7c5ef):
  - 访问修饰符:        java_scope.md → java_modifiers.md
  - final:           java_syntax.md → java_variables.md + java_inheritance.md
  - 删除: autoboxing（KB 无正文）、synchronized（KB 无正文）

修改前自动备份到 data/gt_backup.json。
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.db.session import async_session_factory
from app.models.feedback import EvalQAPair

PY_DS = "66be64a4-5929-4030-9be9-f160955ec948"
JAVA_DS = "09c7c5ef-edc3-42bf-8845-650dbd91a34c"

# (dataset, qa_id_prefix, new_doc_ids)
PY_FIXES = [
    ("2f8dd001", ["10a42fb9-80e8-482c-9d0b-814025627c01"]),   # lambda → controlflow
    ("4739c308", ["671349b3-652a-4971-8e06-885e977eff78"]),   # 列表推导式 → datastructures
    ("85975182", ["49ed9f81-dbfa-47f0-81c7-e2cfd9b0aff0"]),   # pip/venv → venv
    ("871a7570", ["671349b3-652a-4971-8e06-885e977eff78"]),   # list/tuple → datastructures
    ("f8ec2c2d", ["10a42fb9-80e8-482c-9d0b-814025627c01"]),   # 定义函数 → controlflow
]
JAVA_FIXES = [
    ("4f0b0505", ["391dcba2-fa73-4ef2-addb-54ab2cdcfc99"]),   # 访问修饰符 → java_modifiers
    ("e75c7129", [
        "969c55df-b52b-4dc8-9b94-5547802ab3b7",                # java_variables
        "ebf8dd27-0a4b-43fe-95db-106536af52af",                # java_inheritance
    ]),
]
JAVA_DELETE = ["3133d394", "639d87c8"]  # autoboxing, synchronized


async def main():
    backup = []
    async with async_session_factory() as db:
        all_pairs = (await db.execute(select(EvalQAPair))).scalars().all()
        by_prefix = {str(p.id)[:8]: p for p in all_pairs}

        # ── 备份 ──
        for p in all_pairs:
            backup.append({
                "id": str(p.id), "dataset_id": str(p.dataset_id),
                "question": p.question, "doc_ids": [str(x) for x in (p.relevant_doc_ids or [])],
            })
        backup_path = Path(__file__).resolve().parent.parent / "data" / "gt_backup.json"
        backup_path.parent.mkdir(exist_ok=True)
        backup_path.write_text(json.dumps(backup, ensure_ascii=False, indent=2))
        print(f"💾 备份 → {backup_path} ({len(backup)} QA)")

        # ── Python fixes ──
        for qid, new_ids in PY_FIXES:
            p = by_prefix.get(qid)
            if not p:
                print(f"  ⚠️  Python {qid} 未找到"); continue
            old = [str(x) for x in (p.relevant_doc_ids or [])]
            p.relevant_doc_ids = new_ids
            p.ground_truth_notes = f"[GT修复 2026-08-06] {p.ground_truth_notes or ''}（原标注章节归属错误，依据关键词扫描修正）"
            print(f"  ✅ Python {qid} {p.question[:22]}  {old[:2]} → {[x[:8] for x in new_ids]}")

        # ── Java fixes ──
        for qid, new_ids in JAVA_FIXES:
            p = by_prefix.get(qid)
            if not p:
                print(f"  ⚠️  Java {qid} 未找到"); continue
            old = [str(x) for x in (p.relevant_doc_ids or [])]
            p.relevant_doc_ids = new_ids
            p.ground_truth_notes = f"[GT修复 2026-08-06] {p.ground_truth_notes or ''}（原标注章节归属错误）"
            print(f"  ✅ Java {qid} {p.question[:22]}  {old[:2]} → {[x[:8] for x in new_ids]}")

        # ── Java delete ──
        for qid in JAVA_DELETE:
            p = by_prefix.get(qid)
            if not p:
                print(f"  ⚠️  Java {qid} 未找到"); continue
            print(f"  🗑️  删除 Java {qid} {p.question[:22]}（KB 无此主题正文）")
            await db.delete(p)

        await db.commit()
        print("\n✅ 提交完成")


if __name__ == "__main__":
    asyncio.run(main())
