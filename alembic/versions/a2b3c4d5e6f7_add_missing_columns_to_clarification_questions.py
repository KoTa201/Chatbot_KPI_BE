"""add missing columns to clarification_questions

Revision ID: a2b3c4d5e6f7
Revises: c3a71be44b6d
Create Date: 2026-05-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a2b3c4d5e6f7"
down_revision: Union[str, None] = "c3a71be44b6d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE clarification_questions "
        "ADD COLUMN IF NOT EXISTS selected_answer VARCHAR(255)"
    )
    op.execute(
        "ALTER TABLE clarification_questions "
        "ADD COLUMN IF NOT EXISTS free_text_answer VARCHAR(255)"
    )
    op.execute(
        "ALTER TABLE clarification_questions "
        "ADD COLUMN IF NOT EXISTS session_id UUID "
        "REFERENCES chat_sessions(session_id) ON DELETE CASCADE"
    )
    op.create_index(
        "ix_clarification_questions_session_id",
        "clarification_questions",
        ["session_id"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_clarification_questions_session_id",
        table_name="clarification_questions",
    )
    op.drop_column("clarification_questions", "session_id")
    op.drop_column("clarification_questions", "free_text_answer")
    op.drop_column("clarification_questions", "selected_answer")
