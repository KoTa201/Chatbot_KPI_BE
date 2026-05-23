"""drop ambiguous_phrase from clarification_questions

Revision ID: c7d8e9f0a1b2
Revises: 8458b8733e3a
Create Date: 2026-05-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c7d8e9f0a1b2"
down_revision: Union[str, Sequence[str], None] = "8458b8733e3a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("clarification_questions", "ambiguous_phrase")


def downgrade() -> None:
    op.add_column(
        "clarification_questions",
        sa.Column("ambiguous_phrase", sa.String(length=255), nullable=True),
    )
