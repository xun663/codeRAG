"""回填历史知识库的可见性（配合 visibility 语义重构）。

背景：visibility 字段此前从未被权限逻辑执行，platform 库默认值也是 "private"。
新语义下 "private" 表示"调试中隐藏（仅 admin）"，会导致历史 platform 库对普通
用户不可见。本脚本：
  - platform 库 → visibility 归位为 "public"（历史官方库本意公开）
  - personal 库 "shared" → "private"（"shared" 已废弃，历史语义即私有+成员）

用法：cd backend && python scripts/backfill_platform_visibility.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.db.session import async_session_factory  # noqa: E402
from app.models.knowledge_base import KnowledgeBase  # noqa: E402


async def main() -> None:
    async with async_session_factory() as db:
        kbs = (await db.execute(select(KnowledgeBase))).scalars().all()
        changed = 0
        for kb in kbs:
            old = kb.visibility
            if kb.scope == "platform" and old in (None, "shared", "private"):
                kb.visibility = "public"
                changed += 1
                print(f"  platform → public: {kb.name} ({old})")
            elif kb.scope != "platform" and old in (None, "shared"):
                kb.visibility = "private"
                changed += 1
                print(f"  personal → private: {kb.name} ({old})")
        await db.commit()
        print(f"✅ 归位 {changed} 个知识库的可见性（其余保持原值）")


if __name__ == "__main__":
    asyncio.run(main())
