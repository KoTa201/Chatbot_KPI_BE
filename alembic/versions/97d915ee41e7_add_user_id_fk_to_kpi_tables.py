"""add_user_id_fk_to_kpi_tables

Revision ID: 97d915ee41e7
Revises: e08e8e15178a
Create Date: 2026-05-03 15:19:39.811612

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '97d915ee41e7'
down_revision: Union[str, None] = 'e08e8e15178a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    # Truncate semua tabel yang terdampak
    op.execute("TRUNCATE TABLE kpi_tracker_records, kpi_master_records, kpi_groups, ingestion_logs RESTART IDENTITY CASCADE")

    # kpi_master_records: tambah user_id, hapus responsibility_persons
    op.add_column("kpi_master_records",
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True))
    op.drop_column("kpi_master_records", "responsibility_persons")
    op.create_index("ix_kpimaster_user_id", "kpi_master_records", ["user_id"])

    # kpi_tracker_records: tambah user_id, hapus nama_orang
    op.add_column("kpi_tracker_records",
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True))
    op.drop_column("kpi_tracker_records", "nama_orang")
    op.create_index("ix_kpitracker_user_id", "kpi_tracker_records", ["user_id"])


def downgrade():
    op.drop_index("ix_kpimaster_user_id", "kpi_master_records")
    op.drop_column("kpi_master_records", "user_id")
    op.add_column("kpi_master_records",
        sa.Column("responsibility_persons", sa.Text(), nullable=True))

    op.drop_index("ix_kpitracker_user_id", "kpi_tracker_records")
    op.drop_column("kpi_tracker_records", "user_id")
    op.add_column("kpi_tracker_records",
        sa.Column("nama_orang", sa.String(255), nullable=True))