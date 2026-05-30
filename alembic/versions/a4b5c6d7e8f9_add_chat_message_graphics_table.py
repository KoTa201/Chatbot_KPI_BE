"""add chat_message_graphics table

Revision ID: a4b5c6d7e8f9
Revises: f2b7a9c8d1e3
Create Date: 2026-05-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a4b5c6d7e8f9"
down_revision: Union[str, tuple, None] = ("f2b7a9c8d1e3", "b3c4d5e6f7a8")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chat_message_graphics",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chat_messages.message_id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("kpi_name", sa.String(255), nullable=True),
        sa.Column("chart_type", sa.String(50), nullable=False),
        sa.Column("image_url", sa.Text(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("chat_message_graphics")
