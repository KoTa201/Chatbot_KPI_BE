"""replace chat schema

Revision ID: 6fac3aac3721
Revises: a0105384535f
Create Date: 2026-05-20 20:36:20.472358

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "6fac3aac3721"
down_revision: Union[str, None] = "a0105384535f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_clarification_logs_user_id")
    op.execute("DROP INDEX IF EXISTS ix_clarification_logs_session_id")
    op.execute("DROP INDEX IF EXISTS ix_chatbot_audit_log_user_id")
    op.execute("DROP INDEX IF EXISTS ix_chatbot_audit_log_session_id")
    op.execute("DROP INDEX IF EXISTS ix_chat_sessions_user_id")
    op.drop_table("clarification_logs", if_exists=True)
    op.drop_table("chatbot_audit_log", if_exists=True)
    op.drop_table("chat_sessions", if_exists=True)

    op.create_table(
        "chat_sessions",
        sa.Column("session_id", sa.String(length=255), nullable=False),
        sa.Column("session_name", sa.String(length=255), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("chatbot_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["chatbot_id"], ["chatbots.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("session_id"),
    )
    op.create_index("ix_chat_sessions_user_id", "chat_sessions", ["user_id"])
    op.create_index("ix_chat_sessions_chatbot_id", "chat_sessions", ["chatbot_id"])

    op.create_table(
        "chat_messages",
        sa.Column("message_id", sa.String(length=255), nullable=False),
        sa.Column("message", sa.String(length=255), nullable=False),
        sa.Column("is_sender_chatbot", sa.Boolean(), nullable=False),
        sa.Column("send_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("session_id", sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"], ["chat_sessions.session_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("message_id"),
    )
    op.create_index("ix_chat_messages_session_id", "chat_messages", ["session_id"])

    op.create_table(
        "clarification_questions",
        sa.Column("clarification_question_id", sa.String(length=255), nullable=False),
        sa.Column("ambiguous_phrase", sa.String(length=255), nullable=True),
        sa.Column("ambiguity_type", sa.String(length=20), nullable=True),
        sa.Column("clarification_question", sa.String(length=255), nullable=False),
        sa.Column("answer_options", sa.String(length=255), nullable=True),
        sa.Column("user_answer", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("message_id", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(
            ["message_id"], ["chat_messages.message_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("clarification_question_id"),
    )
    op.create_index(
        "ix_clarification_questions_message_id",
        "clarification_questions",
        ["message_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_clarification_questions_message_id", table_name="clarification_questions")
    op.drop_table("clarification_questions")
    op.drop_index("ix_chat_messages_session_id", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index("ix_chat_sessions_chatbot_id", table_name="chat_sessions")
    op.drop_index("ix_chat_sessions_user_id", table_name="chat_sessions")
    op.drop_table("chat_sessions")

    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.String(length=255), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chat_sessions_user_id", "chat_sessions", ["user_id"])

    op.create_table(
        "chatbot_audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", sa.String(length=255), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_role", sa.String(length=20), nullable=True),
        sa.Column("user_query", sa.Text(), nullable=True),
        sa.Column("generated_sql", sa.Text(), nullable=True),
        sa.Column("wireguard_status", sa.String(length=10), nullable=True),
        sa.Column("wireguard_reason", sa.Text(), nullable=True),
        sa.Column("execution_status", sa.String(length=20), nullable=True),
        sa.Column("rows_returned", sa.Integer(), nullable=True),
        sa.Column("execution_time_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chatbot_audit_log_session_id", "chatbot_audit_log", ["session_id"])
    op.create_index("ix_chatbot_audit_log_user_id", "chatbot_audit_log", ["user_id"])

    op.create_table(
        "clarification_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", sa.String(length=255), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_role", sa.String(length=50), nullable=False),
        sa.Column("original_query", sa.Text(), nullable=False),
        sa.Column("ambiguity_score", sa.Numeric(precision=3, scale=2), nullable=False),
        sa.Column("ambiguity_type", sa.String(length=50), nullable=False),
        sa.Column("decision", sa.String(length=10), nullable=False),
        sa.Column("decision_source", sa.String(length=20), nullable=False),
        sa.Column("clarifying_question", sa.Text(), nullable=True),
        sa.Column("clarification_answer", sa.Text(), nullable=True),
        sa.Column("disambiguated_query", sa.Text(), nullable=True),
        sa.Column("user_feedback", sa.Boolean(), nullable=True),
        sa.Column("needed_correction", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_clarification_logs_session_id", "clarification_logs", ["session_id"])
    op.create_index("ix_clarification_logs_user_id", "clarification_logs", ["user_id"])
