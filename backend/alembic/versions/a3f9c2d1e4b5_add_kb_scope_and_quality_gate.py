"""add_kb_scope_and_quality_gate

知识库双层模型 + 质量门禁字段：
  - scope: platform（平台策展库，仅 admin 可建）/ personal（个人库，隔离）
  - quality_status: not_checked / verified / unverified / no_qa_data
  - quality_metrics_json: 最近一次门禁评估的完整指标

Revision ID: a3f9c2d1e4b5
Revises: 53986c7c67c6
Create Date: 2026-08-15 21:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3f9c2d1e4b5'
down_revision: Union[str, Sequence[str], None] = '53986c7c67c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('knowledge_bases', sa.Column('scope', sa.String(length=20), nullable=False, server_default='personal'))
    op.add_column('knowledge_bases', sa.Column('quality_status', sa.String(length=20), nullable=False, server_default='not_checked'))
    op.add_column('knowledge_bases', sa.Column('quality_metrics_json', sa.JSON(), nullable=True))
    # 存量知识库（Python/Java 教程）均为平台策展库
    op.execute("UPDATE knowledge_bases SET scope = 'platform'")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('knowledge_bases', 'quality_metrics_json')
    op.drop_column('knowledge_bases', 'quality_status')
    op.drop_column('knowledge_bases', 'scope')
