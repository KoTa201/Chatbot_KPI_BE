"""normalize clarification answer options

Revision ID: d1e2f3a4b5c6
Revises: a42fff81daea
Create Date: 2026-05-30

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, Sequence[str], None] = "a42fff81daea"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "clarification_question_answer_options",
        sa.Column("id", sa.String(255), nullable=False),
        sa.Column(
            "clarification_question_id",
            sa.String(255),
            nullable=False,
        ),
        sa.Column("option_text", sa.Text(), nullable=False),
        sa.Column(
            "option_order",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.ForeignKeyConstraint(
            ["clarification_question_id"],
            ["clarification_questions.clarification_question_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_clarification_answer_options_question_id",
        "clarification_question_answer_options",
        ["clarification_question_id"],
        unique=False,
    )
    op.drop_column("clarification_questions", "answer_options")


def downgrade() -> None:
    op.add_column(
        "clarification_questions",
        sa.Column("answer_options", sa.Text(), nullable=True),
    )
    op.drop_index(
        "ix_clarification_answer_options_question_id",
        table_name="clarification_question_answer_options",
    )
    op.drop_table("clarification_question_answer_options")
