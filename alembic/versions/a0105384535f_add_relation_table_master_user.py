"""add_relation_table_master_user

Revision ID: a0105384535f
Revises: 97d915ee41e7
Create Date: 2026-05-03 16:25:34.021234

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a0105384535f'
down_revision: Union[str, None] = '97d915ee41e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. Buat tabel junction ──────────────────────────────────────────────
    op.create_table(
        "kpi_master_users",
        sa.Column(
            "kpi_master_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["kpi_master_id"],
            ["kpi_master_records.id"],
            name="fk_kpimasterusers_master",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_kpimasterusers_user",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("kpi_master_id", "user_id", name="pk_kpi_master_users"),
    )
 
    # Index agar query "semua KPI milik user X" tetap efisien
    op.create_index(
        "ix_kpimasterusers_user_id",
        "kpi_master_users",
        ["user_id"],
    )
 
    # ── 2. Migrasikan data user_id lama ke junction table ──────────────────
    #    Setiap baris kpi_master_records yang punya user_id ≠ NULL
    #    dijadikan satu baris di kpi_master_users.
    op.execute(
        """
        INSERT INTO kpi_master_users (kpi_master_id, user_id)
        SELECT id, user_id
        FROM   kpi_master_records
        WHERE  user_id IS NOT NULL
        """
    )
 
    # ── 3. Hapus artefak lama dari kpi_master_records ─────────────────────
    op.drop_index("ix_kpimaster_user_id", table_name="kpi_master_records")
    op.drop_constraint(
        "fk_kpimaster_user_id",
        "kpi_master_records",
        type_="foreignkey",
    )
    op.drop_column("kpi_master_records", "user_id")
 
 
def downgrade() -> None:
    # ── 1. Kembalikan kolom user_id ke kpi_master_records ─────────────────
    op.add_column(
        "kpi_master_records",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="PIC utama; migrasi dari responsibility_persons (nama pertama).",
        ),
    )
    op.create_foreign_key(
        "fk_kpimaster_user_id",
        "kpi_master_records",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_kpimaster_user_id",
        "kpi_master_records",
        ["user_id"],
    )
 
    # ── 2. Restore satu user_id per KPI dari junction table (PIC pertama) ─
    op.execute(
        """
        UPDATE kpi_master_records AS k
        SET    user_id = (
            SELECT user_id
            FROM   kpi_master_users
            WHERE  kpi_master_id = k.id
            LIMIT  1
        )
        """
    )
 
    # ── 3. Hapus junction table ────────────────────────────────────────────
    op.drop_index("ix_kpimasterusers_user_id", table_name="kpi_master_users")
    op.drop_table("kpi_master_users")
 