"""Create kpi_master_records table

Revision ID: 007_create_kpi_master_records
Revises: 006_create_kpi_groups
Create Date: 2026-04-17 14:26:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "007_create_kpi_master_records"
down_revision: Union[str, None] = "006_create_kpi_groups"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "kpi_master_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tahun", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=255), nullable=False),
        sa.Column("kpi_name", sa.String(length=255), nullable=False),
        sa.Column("definisi_operasional", sa.Text(), nullable=True),
        sa.Column("target", sa.String(length=100), nullable=True),
        sa.Column("achieve", sa.String(length=100), nullable=True),
        sa.Column("partial", sa.String(length=100), nullable=True),
        sa.Column("fail", sa.String(length=100), nullable=True),
        sa.Column("responsibility_persons", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["kpi_groups.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("group_id", "kpi_name", name="uq_kpimaster_group_name"),
    )
    op.create_index("ix_kpimaster_group_category", "kpi_master_records", ["group_id", "category"])


def downgrade() -> None:
    op.drop_index("ix_kpimaster_group_category", table_name="kpi_master_records")
    op.drop_table("kpi_master_records")
