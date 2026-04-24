"""Scheduler: interval_value Integer→DateTime, drop interval_unit, drop trigger_dates

Revision ID: 013_scheduler_monthly_cron
Revises: 012_extend_clarification_logs_decision_source
Create Date: 2026-04-24 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "013_scheduler_monthly_cron"
down_revision: Union[str, None] = "012_extend_clarification_logs_decision_source"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Convert interval_value from INTEGER to TIMESTAMP WITH TIME ZONE.
    # Existing rows get day=1, hour=0 as a safe default.
    op.alter_column(
        "scheduler_configs",
        "interval_value",
        type_=sa.DateTime(timezone=True),
        postgresql_using="'1900-01-01 00:00:00+00'::TIMESTAMP WITH TIME ZONE",
        nullable=True,
        existing_nullable=True,
    )
    op.drop_column("scheduler_configs", "interval_unit")
    # trigger_dates may have been added outside migrations; drop safely.
    op.execute("ALTER TABLE scheduler_configs DROP COLUMN IF EXISTS trigger_dates")


def downgrade() -> None:
    op.execute(
        "ALTER TABLE scheduler_configs ADD COLUMN IF NOT EXISTS "
        "trigger_dates JSON"
    )
    op.add_column(
        "scheduler_configs",
        sa.Column("interval_unit", sa.String(length=20), nullable=True),
    )
    op.alter_column(
        "scheduler_configs",
        "interval_value",
        type_=sa.Integer(),
        postgresql_using="12",
        nullable=True,
        existing_nullable=True,
    )
