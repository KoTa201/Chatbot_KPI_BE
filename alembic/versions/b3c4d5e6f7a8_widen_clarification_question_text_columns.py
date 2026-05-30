"""widen clarification_questions text columns to TEXT

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-05-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b3c4d5e6f7a8"
down_revision: Union[str, None] = "a2b3c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "clarification_questions", "clarification_question",
        type_=sa.Text(), existing_nullable=False,
    )
    op.alter_column(
        "clarification_questions", "answer_options",
        type_=sa.Text(), existing_nullable=True,
    )
    op.alter_column(
        "clarification_questions", "selected_answer",
        type_=sa.Text(), existing_nullable=True,
    )
    op.alter_column(
        "clarification_questions", "free_text_answer",
        type_=sa.Text(), existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "clarification_questions", "free_text_answer",
        type_=sa.String(255), existing_nullable=True,
    )
    op.alter_column(
        "clarification_questions", "selected_answer",
        type_=sa.String(255), existing_nullable=True,
    )
    op.alter_column(
        "clarification_questions", "answer_options",
        type_=sa.String(255), existing_nullable=True,
    )
    op.alter_column(
        "clarification_questions", "clarification_question",
        type_=sa.String(255), existing_nullable=False,
    )
