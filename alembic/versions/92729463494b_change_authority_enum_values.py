"""change_authority_enum_values

Revision ID: 92729463494b
Revises: dd92dd2b0ccf
Create Date: 2026-05-01 10:04:43.241328

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '92729463494b'
down_revision: Union[str, None] = 'dd92dd2b0ccf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE authorityenum RENAME VALUE 'KARYAWAN' TO 'karyawan'")


def downgrade() -> None:
    op.execute("ALTER TYPE authorityenum RENAME VALUE 'karyawan' TO 'KARYAWAN'")
