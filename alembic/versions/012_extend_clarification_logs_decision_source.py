"""Extend clarification_logs.decision_source column to accommodate 'llm_fallback'

Revision ID: 012_extend_clarification_logs_decision_source
Revises: 011_create_kpi_tracker_records
Create Date: 2026-04-18 02:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "012_extend_clarification_logs_decision_source"
down_revision: Union[str, None] = "011_create_kpi_tracker_records"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Extend the decision_source column from VARCHAR(10) to VARCHAR(20)
    # to accommodate the new 'llm_fallback' value (11 characters)
    op.alter_column(
        "clarification_logs",
        "decision_source",
        type_=sa.String(length=20),
        existing_type=sa.String(length=10),
        nullable=False,
    )


def downgrade() -> None:
    # Revert back to VARCHAR(10) in case of rollback
    op.alter_column(
        "clarification_logs",
        "decision_source",
        type_=sa.String(length=10),
        existing_type=sa.String(length=20),
        nullable=False,
    )
