#!/usr/bin/env python3
"""清理误导入的重复评估数据集。

背景: Python/Java KB 各有 3-4 份数据集副本（"问答集 v2" 被重复导入 3 次），
其中只有 fix_gt.py 修正过的那份（Python: 66be64a4, Java: 09c7c5ef）标注可信。
其余副本会导致质量门禁/评估选择到错误标注。

处理: 删除重复数据集（级联删除其 QA pairs + eval results），删除前完整备份。
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, select

from app.db.session import async_session_factory
from app.models.feedback import EvalDataset, EvalQAPair, EvalResult

# fix_gt.py 修正过的可信数据集（唯一保留）
KEEP_DATASETS = {
    "66be64a4-5929-4030-9be9-f160955ec948",  # Python 问答集 v2 (fixed)
    "09c7c5ef-edc3-42bf-8845-650dbd91a34c",  # Java 问答集 v2 (fixed)
}


async def main() -> None:
    async with async_session_factory() as db:
        datasets = (await db.execute(select(EvalDataset))).scalars().all()
        to_delete = [d for d in datasets if str(d.id) not in KEEP_DATASETS]

        if not to_delete:
            print("没有需要清理的重复数据集")
            return

        # ── 备份 ──
        backup = {"created_at": datetime.now().isoformat(), "datasets": []}
        for d in to_delete:
            pairs = (await db.execute(
                select(EvalQAPair).where(EvalQAPair.dataset_id == d.id)
            )).scalars().all()
            backup["datasets"].append({
                "id": str(d.id), "name": d.name, "kb_id": str(d.kb_id),
                "created_at": d.created_at.isoformat() if d.created_at else None,
                "qa_pairs": [
                    {
                        "id": str(p.id), "question": p.question,
                        "reference_answer": p.reference_answer,
                        "relevant_doc_ids": p.relevant_doc_ids,
                        "ground_truth_chunk_ids": p.ground_truth_chunk_ids,
                        "expected_chunk_ids": p.expected_chunk_ids,
                    }
                    for p in pairs
                ],
            })
        out = Path(__file__).resolve().parent.parent / "data" / "dup_datasets_backup.json"
        out.write_text(json.dumps(backup, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"已备份 {len(backup['datasets'])} 个数据集 → {out}")

        # ── 删除（EvalResult/QAPair 级联）──
        total_pairs = 0
        for d in to_delete:
            pair_ids = (await db.execute(
                select(EvalQAPair.id).where(EvalQAPair.dataset_id == d.id)
            )).scalars().all()
            if pair_ids:
                await db.execute(delete(EvalResult).where(EvalResult.qa_pair_id.in_(pair_ids)))
                total_pairs += len(pair_ids)
            await db.execute(delete(EvalQAPair).where(EvalQAPair.dataset_id == d.id))
            await db.execute(delete(EvalDataset).where(EvalDataset.id == d.id))
            print(f"  删除数据集 {d.name} ({str(d.id)[:8]}), {len(pair_ids)} 对 QA")
        await db.commit()
        print(f"完成: 删除 {len(to_delete)} 个数据集, 共 {total_pairs} 对 QA")


if __name__ == "__main__":
    asyncio.run(main())
