"""merge chat graphics and clarification heads

Revision ID: b7383c868bf5
Revises: a4b5c6d7e8f9, b3c4d5e6f7a8
Create Date: 2026-05-30 07:33:00.062146

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7383c868bf5'
down_revision: Union[str, None] = ('a4b5c6d7e8f9', 'b3c4d5e6f7a8')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
