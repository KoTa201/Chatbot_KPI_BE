"""Create chatbot_audit_log table

Revision ID: 005_create_chatbot_audit_log
Revises: 001_create_users
Create Date: 2026-04-17 14:24:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "005_create_chatbot_audit_log"
down_revision: Union[str, None] = "001_create_users"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
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
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_chatbot_audit_log_session_id"), "chatbot_audit_log", ["session_id"])
    op.create_index(op.f("ix_chatbot_audit_log_user_id"), "chatbot_audit_log", ["user_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_chatbot_audit_log_user_id"), table_name="chatbot_audit_log")
    op.drop_index(op.f("ix_chatbot_audit_log_session_id"), table_name="chatbot_audit_log")
    op.drop_table("chatbot_audit_log")
