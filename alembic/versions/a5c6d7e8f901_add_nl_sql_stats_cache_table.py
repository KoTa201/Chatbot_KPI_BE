"""add nl_sql_stats_cache table

Revision ID: a5c6d7e8f901
Revises: 3f4a5b6c7d8e
Create Date: 2026-07-03 00:00:00.000000

Cache singleton (satu baris, id=1) untuk statistik kolom NL-to-SQL.
Level aplikasi (tabel biasa + kolom TEXT) — bukan CREATE VIEW / MATERIALIZED VIEW,
agar portable lintas database engine dan hasil bisa diformat jadi teks siap-prompt.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a5c6d7e8f901"
down_revision: Union[str, tuple, None] = "3f4a5b6c7d8e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "nl_sql_stats_cache",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("stats_json", sa.Text(), nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("nl_sql_stats_cache")
