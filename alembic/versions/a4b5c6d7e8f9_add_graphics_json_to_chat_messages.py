"""add graphics_json to chat_messages

Revision ID: a4b5c6d7e8f9
Revises: f2b7a9c8d1e3
Create Date: 2026-05-29 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a4b5c6d7e8f9"
down_revision: Union[str, None] = "f2b7a9c8d1e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "chat_messages",
        sa.Column("graphics_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("chat_messages", "graphics_json")
