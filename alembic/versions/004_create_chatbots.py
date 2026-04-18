"""Create chatbots table

Revision ID: 004_create_chatbots
Revises: 001_create_users
Create Date: 2026-04-17 14:23:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "004_create_chatbots"
down_revision: Union[str, None] = "001_create_users"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_enum("authoritye_enum", ["HRD", "Karyawan"], schema=None)
    
    op.create_table(
        "chatbots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("nama_chatbot", sa.String(length=255), nullable=False),
        sa.Column("otoritas", sa.Enum("HRD", "Karyawan", name="authoritye_enum"), nullable=False),
        sa.Column("addon_prompt", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_chatbots_id"), "chatbots", ["id"], unique=True)
    op.create_index(op.f("ix_chatbots_nama_chatbot"), "chatbots", ["nama_chatbot"])


def downgrade() -> None:
    op.drop_index(op.f("ix_chatbots_nama_chatbot"), table_name="chatbots")
    op.drop_index(op.f("ix_chatbots_id"), table_name="chatbots")
    op.drop_table("chatbots")
    op.drop_enum("authoritye_enum", schema=None)
