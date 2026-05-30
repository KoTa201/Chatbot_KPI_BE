"""merge roleenum and kpi group branches

Revision ID: b4a1f2c9d8e7
Revises: d2f4a0bc9e31, 882efcc394a8
Create Date: 2026-04-29 14:05:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b4a1f2c9d8e7'
down_revision: Union[str, tuple[str, str], None] = ('d2f4a0bc9e31', '882efcc394a8')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass