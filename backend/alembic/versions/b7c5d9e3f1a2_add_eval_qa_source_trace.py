"""add_eval_qa_source_trace

自动质量门禁溯源字段：EvalQAPair 增加出题来源文档/chunk 的稳定身份、
chunk 内容哈希、题型、评估元数据与 stale 标记，支撑"自动出题驱动检索门禁"
且重索引后 GT 可通过 content hash 找回（避免 Chunk ID 失效）。

Revision ID: b7c5d9e3f1a2
Revises: a4b2c8d6e0f4
Create Date: 2026-08-25 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7c5d9e3f1a2'
down_revision: Union[str, Sequence[str], None] = 'a4b2c8d6e0f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('eval_qa_pairs', sa.Column('source_document_id', sa.String(length=36), nullable=True))
    op.add_column('eval_qa_pairs', sa.Column('source_document_hash', sa.String(length=64), nullable=True))
    op.add_column('eval_qa_pairs', sa.Column('source_chunk_id', sa.String(length=36), nullable=True))
    op.add_column('eval_qa_pairs', sa.Column('chunk_content_hash', sa.String(length=64), nullable=True))
    op.add_column('eval_qa_pairs', sa.Column('question_type', sa.String(length=20), nullable=True))
    op.add_column('eval_qa_pairs', sa.Column('eval_metadata', sa.JSON(), nullable=True))
    op.add_column('eval_qa_pairs', sa.Column('is_stale', sa.Boolean(), nullable=False, server_default=sa.text("FALSE")))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('eval_qa_pairs', 'is_stale')
    op.drop_column('eval_qa_pairs', 'eval_metadata')
    op.drop_column('eval_qa_pairs', 'question_type')
    op.drop_column('eval_qa_pairs', 'chunk_content_hash')
    op.drop_column('eval_qa_pairs', 'source_chunk_id')
    op.drop_column('eval_qa_pairs', 'source_document_hash')
    op.drop_column('eval_qa_pairs', 'source_document_id')
