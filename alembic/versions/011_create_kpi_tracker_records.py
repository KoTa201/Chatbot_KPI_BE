"""Create kpi_tracker_records table

Revision ID: 011_create_kpi_tracker_records
Revises: 010_create_clarification_logs
Create Date: 2026-04-17 14:29:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "011_create_kpi_tracker_records"
down_revision: Union[str, None] = "010_create_clarification_logs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "kpi_tracker_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kpi_master_id", postgresql.UUID(
            as_uuid=True), nullable=False),
        sa.Column("nama_orang", sa.String(length=255), nullable=False),
        sa.Column("realisasi", sa.String(length=100), nullable=True),
        sa.Column("keterangan", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["group_id"], ["kpi_groups.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["kpi_master_id"], ["kpi_master_records.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_kpitracker_group_orang",
                    "kpi_tracker_records", ["group_id", "nama_orang"])
    op.create_index("ix_kpitracker_master_orang", "kpi_tracker_records", [
                    "kpi_master_id", "nama_orang"])
    op.create_index("ix_kpitracker_created_brin", "kpi_tracker_records", [
                    "created_at"], postgresql_using="brin")


def downgrade() -> None:
    op.drop_index("ix_kpitracker_created_brin",
                  table_name="kpi_tracker_records")
    op.drop_index("ix_kpitracker_master_orang",
                  table_name="kpi_tracker_records")
    op.drop_index("ix_kpitracker_group_orang",
                  table_name="kpi_tracker_records")
    op.drop_table("kpi_tracker_records")
