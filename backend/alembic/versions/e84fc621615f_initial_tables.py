"""initial_tables — create all application tables

Revision ID: e84fc621615f
Revises:
Create Date: 2026-07-16 09:22:17.578871
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic
revision: str = "e84fc621615f"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create all application tables."""

    # ── users ────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("username", sa.String(50), unique=True, nullable=False, index=True),
        sa.Column("email", sa.String(255), unique=True, nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(100), nullable=True),
        sa.Column("role", sa.String(20), nullable=False, server_default="learner"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("TRUE")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    # ── knowledge_bases ───────────────────────────────────────────
    op.create_table(
        "knowledge_bases",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("owner_id", sa.CHAR(36), nullable=False),
        sa.Column("kb_type", sa.String(20), nullable=False),
        sa.Column("visibility", sa.String(20), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("doc_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("vector_db_name", sa.String(100), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
    )

    # ── operation_logs ────────────────────────────────────────────
    op.create_table(
        "operation_logs",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("user_id", sa.CHAR(36), nullable=True),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("resource_type", sa.String(30), nullable=True),
        sa.Column("resource_id", sa.CHAR(36), nullable=True),
        sa.Column("detail_json", sa.JSON(), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    )

    # ── system_config ─────────────────────────────────────────────
    op.create_table(
        "system_config",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("config_key", sa.String(100), unique=True, nullable=False),
        sa.Column("config_value", sa.JSON(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("updated_by", sa.CHAR(36), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
    )

    # ── conversations ─────────────────────────────────────────────
    op.create_table(
        "conversations",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("user_id", sa.CHAR(36), nullable=False),
        sa.Column("kb_id", sa.CHAR(36), nullable=True),
        sa.Column("title", sa.String(200), nullable=True),
        sa.Column("context_summary", sa.Text(), nullable=True),
        sa.Column("message_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["kb_id"], ["knowledge_bases.id"]),
    )

    # ── documents ─────────────────────────────────────────────────
    op.create_table(
        "documents",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("kb_id", sa.CHAR(36), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("source_type", sa.String(20), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("file_path", sa.Text(), nullable=True),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column("mime_type", sa.String(100), nullable=True),
        sa.Column("doc_hash", sa.String(64), nullable=True),
        sa.Column("word_count", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["kb_id"], ["knowledge_bases.id"], ondelete="CASCADE"),
    )

    # ── eval_datasets ─────────────────────────────────────────────
    op.create_table(
        "eval_datasets",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("kb_id", sa.CHAR(36), nullable=True),
        sa.Column("created_by", sa.CHAR(36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["kb_id"], ["knowledge_bases.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
    )

    # ── kb_members ────────────────────────────────────────────────
    op.create_table(
        "kb_members",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("kb_id", sa.CHAR(36), nullable=False),
        sa.Column("user_id", sa.CHAR(36), nullable=False),
        sa.Column("permission", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("kb_id", "user_id", name="uq_kb_members"),
        sa.ForeignKeyConstraint(["kb_id"], ["knowledge_bases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )

    # ── learning_paths ────────────────────────────────────────────
    op.create_table(
        "learning_paths",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("kb_id", sa.CHAR(36), nullable=False),
        sa.Column("concept_a", sa.String(200), nullable=False),
        sa.Column("concept_b", sa.String(200), nullable=False),
        sa.Column("relationship", sa.String(30), nullable=False),
        sa.Column("strength", sa.Float(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("kb_id", "concept_a", "concept_b", name="uq_learning_paths"),
        sa.ForeignKeyConstraint(["kb_id"], ["knowledge_bases.id"], ondelete="CASCADE"),
    )

    # ── document_chunks ───────────────────────────────────────────
    op.create_table(
        "document_chunks",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("doc_id", sa.CHAR(36), nullable=False),
        sa.Column("kb_id", sa.CHAR(36), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_preview", sa.String(200), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("vector_id", sa.String(200), nullable=True),
        sa.Column("chunk_type", sa.String(30), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["doc_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["kb_id"], ["knowledge_bases.id"], ondelete="CASCADE"),
    )

    # ── eval_qa_pairs ─────────────────────────────────────────────
    op.create_table(
        "eval_qa_pairs",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("dataset_id", sa.CHAR(36), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("reference_answer", sa.Text(), nullable=True),
        sa.Column("expected_chunk_ids", sa.JSON(), nullable=True),
        sa.Column("difficulty", sa.String(10), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["dataset_id"], ["eval_datasets.id"], ondelete="CASCADE"),
    )

    # ── experiments ───────────────────────────────────────────────
    op.create_table(
        "experiments",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_by", sa.CHAR(36), nullable=False),
        sa.Column("dataset_id", sa.CHAR(36), nullable=False),
        sa.Column("config_a", sa.JSON(), nullable=False),
        sa.Column("config_b", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("results_json", sa.JSON(), nullable=True),
        sa.Column("winner", sa.String(1), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["dataset_id"], ["eval_datasets.id"]),
    )

    # ── messages ──────────────────────────────────────────────────
    op.create_table(
        "messages",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("conversation_id", sa.CHAR(36), nullable=False),
        sa.Column("role", sa.String(10), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_type", sa.String(20), nullable=False),
        sa.Column("retrieval_config", sa.JSON(), nullable=True),
        sa.Column("retrieved_chunks", sa.JSON(), nullable=True),
        sa.Column("llm_provider", sa.String(30), nullable=True),
        sa.Column("llm_model", sa.String(100), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("user_rating", sa.SmallInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
    )

    # ── eval_results ──────────────────────────────────────────────
    op.create_table(
        "eval_results",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("qa_pair_id", sa.CHAR(36), nullable=False),
        sa.Column("experiment_id", sa.CHAR(36), nullable=True),
        sa.Column("recall_at_1", sa.Float(), nullable=True),
        sa.Column("recall_at_3", sa.Float(), nullable=True),
        sa.Column("recall_at_5", sa.Float(), nullable=True),
        sa.Column("mrr", sa.Float(), nullable=True),
        sa.Column("precision_at_k", sa.Float(), nullable=True),
        sa.Column("faithfulness", sa.Float(), nullable=True),
        sa.Column("pass_at_1", sa.Float(), nullable=True),
        sa.Column("pass_at_k", sa.Float(), nullable=True),
        sa.Column("generated_answer", sa.Text(), nullable=True),
        sa.Column("retrieved_chunk_ids", sa.JSON(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["qa_pair_id"], ["eval_qa_pairs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["experiment_id"], ["experiments.id"]),
    )

    # ── exercises ─────────────────────────────────────────────────
    op.create_table(
        "exercises",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("chunk_id", sa.CHAR(36), nullable=False),
        sa.Column("kb_id", sa.CHAR(36), nullable=False),
        sa.Column("doc_id", sa.CHAR(36), nullable=True),
        sa.Column("type", sa.String(30), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("options", sa.JSON(), nullable=False),
        sa.Column("answer", sa.String(1), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("difficulty", sa.String(10), nullable=False),
        sa.Column("priority", sa.String(10), nullable=False),
        sa.Column("topic", sa.String(100), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["chunk_id"], ["document_chunks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["kb_id"], ["knowledge_bases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["doc_id"], ["documents.id"], ondelete="SET NULL"),
    )

    # ── feedback_details ──────────────────────────────────────────
    op.create_table(
        "feedback_details",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("message_id", sa.CHAR(36), nullable=False),
        sa.Column("user_id", sa.CHAR(36), nullable=False),
        sa.Column("rating", sa.SmallInteger(), nullable=False),
        sa.Column("feedback_type", sa.String(20), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("is_helpful", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    )

    # ── exercise_states ───────────────────────────────────────────
    op.create_table(
        "exercise_states",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("user_id", sa.CHAR(36), nullable=False),
        sa.Column("exercise_id", sa.CHAR(36), nullable=False),
        sa.Column("interval", sa.Integer(), nullable=False, server_default=sa.text("0")),                    # noqa: F601
        sa.Column("ease_factor", sa.Float(), nullable=False, server_default=sa.text("2.5")),
        sa.Column("repetitions", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("due_date", sa.DateTime(), nullable=False),
        sa.Column("last_quality", sa.Integer(), nullable=True),
        sa.Column("consecutive_correct", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("consecutive_wrong", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("total_attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("total_correct", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("is_mastered", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "exercise_id", name="uq_exercise_states"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["exercise_id"], ["exercises.id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    """Drop all application tables (reverse order of creation)."""
    op.drop_table("exercise_states")
    op.drop_table("feedback_details")
    op.drop_table("exercises")
    op.drop_table("eval_results")
    op.drop_table("messages")
    op.drop_table("experiments")
    op.drop_table("eval_qa_pairs")
    op.drop_table("document_chunks")
    op.drop_table("learning_paths")
    op.drop_table("kb_members")
    op.drop_table("eval_datasets")
    op.drop_table("documents")
    op.drop_table("conversations")
    op.drop_table("system_config")
    op.drop_table("operation_logs")
    op.drop_table("knowledge_bases")
    op.drop_table("users")
