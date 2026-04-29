"""drop_is_scheduled_from_kpi_groups

Revision ID: 882efcc394a8
Revises: 8b7c43c2805b
Create Date: 2026-04-29 13:31:50.992554

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '882efcc394a8'
down_revision: Union[str, None] = '8b7c43c2805b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('kpi_groups', 'is_scheduled')


def downgrade() -> None:
    op.add_column('kpi_groups', sa.Column(
        'is_scheduled',
        sa.BOOLEAN(),
        server_default=sa.text('true'),
        nullable=False,
    ))
