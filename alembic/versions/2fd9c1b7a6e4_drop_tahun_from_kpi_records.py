"""drop_tahun_from_kpi_records

Revision ID: 2fd9c1b7a6e4
Revises: a0105384535f
Create Date: 2026-05-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "2fd9c1b7a6e4"
down_revision: Union[str, None] = "a0105384535f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE kpi_master_records DROP COLUMN IF EXISTS tahun")
    op.execute("ALTER TABLE kpi_tracker_records DROP COLUMN IF EXISTS tahun")


def downgrade() -> None:
    op.add_column(
        "kpi_tracker_records",
        sa.Column("tahun", sa.Integer(), nullable=True),
    )
    op.add_column(
        "kpi_master_records",
        sa.Column("tahun", sa.Integer(), nullable=True),
    )
