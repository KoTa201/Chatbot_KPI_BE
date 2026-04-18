"""Create ingestion_logs table

Revision ID: 009_create_ingestion_logs
Revises: 006_create_kpi_groups, 008_create_scheduler_configs
Create Date: 2026-04-17 14:28:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "009_create_ingestion_logs"
down_revision: Union[str, None] = ["006_create_kpi_groups", "008_create_scheduler_configs"]
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ingestion_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kpi_group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scheduler_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("total_rows", sa.Integer(), nullable=False),
        sa.Column("ingested_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("errors", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('success', 'failed')", name="ck_ingestion_status"),
        sa.ForeignKeyConstraint(["kpi_group_id"], ["kpi_groups.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["scheduler_id"], ["scheduler_configs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ingestion_scheduler_status", "ingestion_logs", ["scheduler_id", "status"])
    op.create_index("ix_ingestion_created_brin", "ingestion_logs", ["created_at"], postgresql_using="brin")
    op.create_index("ix_ingestion_kpi_group", "ingestion_logs", ["kpi_group_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_ingestion_kpi_group", table_name="ingestion_logs")
    op.drop_index("ix_ingestion_created_brin", table_name="ingestion_logs")
    op.drop_index("ix_ingestion_scheduler_status", table_name="ingestion_logs")
    op.drop_table("ingestion_logs")
