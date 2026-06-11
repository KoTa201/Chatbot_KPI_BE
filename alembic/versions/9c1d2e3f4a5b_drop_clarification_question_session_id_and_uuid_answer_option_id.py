"""drop clarification question session_id and uuid answer option id

Revision ID: 9c1d2e3f4a5b
Revises: e0e734257a49
Create Date: 2026-06-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "9c1d2e3f4a5b"
down_revision: Union[str, Sequence[str], None] = "e0e734257a49"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index(
        "ix_clarification_questions_session_id",
        table_name="clarification_questions",
        if_exists=True,
    )
    op.drop_column("clarification_questions", "session_id")
    op.alter_column(
        "clarification_question_answer_options",
        "id",
        existing_type=sa.String(length=255),
        type_=postgresql.UUID(as_uuid=True),
        existing_nullable=False,
        postgresql_using="id::uuid",
    )


def downgrade() -> None:
    op.alter_column(
        "clarification_question_answer_options",
        "id",
        existing_type=postgresql.UUID(as_uuid=True),
        type_=sa.String(length=255),
        existing_nullable=False,
        postgresql_using="id::text",
    )
    op.add_column(
        "clarification_questions",
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "clarification_questions_session_id_fkey",
        "clarification_questions",
        "chat_sessions",
        ["session_id"],
        ["session_id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_clarification_questions_session_id",
        "clarification_questions",
        ["session_id"],
        unique=False,
    )
