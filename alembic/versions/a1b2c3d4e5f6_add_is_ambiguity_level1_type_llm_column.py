"""add is ambiguity level1 type llm column

Revision ID: a1b2c3d4e5f6
Revises: 6fac3aac3721
Create Date: 2026-05-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "6fac3aac3721"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "clarification_questions",
        sa.Column("is_ambiguity_level1_type_llm", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("clarification_questions", "is_ambiguity_level1_type_llm")
