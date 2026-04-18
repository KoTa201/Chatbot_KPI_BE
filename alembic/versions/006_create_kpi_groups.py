"""Create kpi_groups table

Revision ID: 006_create_kpi_groups
Revises: 001_create_users
Create Date: 2026-04-17 14:25:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "006_create_kpi_groups"
down_revision: Union[str, None] = "001_create_users"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_enum("grouptypee_enum", ["master", "tracker"], schema=None)
    
    op.create_table(
        "kpi_groups",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("group_type", sa.Enum("master", "tracker", name="grouptypee_enum"), nullable=False),
        sa.Column("sheet_id", sa.String(length=255), nullable=True),
        sa.Column("sheet_url", sa.String(length=512), nullable=True),
        sa.Column("sheet_name", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_kpi_groups_id"), "kpi_groups", ["id"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_kpi_groups_id"), table_name="kpi_groups")
    op.drop_table("kpi_groups")
    op.drop_enum("grouptypee_enum", schema=None)
