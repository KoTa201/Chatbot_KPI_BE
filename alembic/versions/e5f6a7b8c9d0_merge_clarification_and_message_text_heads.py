"""merge clarification and message text heads

Revision ID: e5f6a7b8c9d0
Revises: c7d8e9f0a1b2, d4e5f6a7b8c9
Create Date: 2026-05-23

"""
from typing import Sequence, Union


revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = ("c7d8e9f0a1b2", "d4e5f6a7b8c9")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
