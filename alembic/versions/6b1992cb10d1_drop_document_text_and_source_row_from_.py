"""drop document_text and source_row from kpi_tracker_record

Revision ID: 6b1992cb10d1
Revises: f9c96abf52bc
Create Date: 2026-04-25 12:13:42.858675

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = '6b1992cb10d1'
down_revision: Union[str, None] = 'f9c96abf52bc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [col['name']
               for col in inspector.get_columns('kpi_tracker_records')]

    if 'document_text' in columns:
        op.drop_column('kpi_tracker_records', 'document_text')

    if 'source_row' in columns:
        op.drop_column('kpi_tracker_records', 'source_row')


def downgrade():
    op.add_column('kpi_tracker_records',
                  sa.Column('document_text', sa.Text(), nullable=True), schema='public')
    op.add_column('kpi_tracker_records',
                  sa.Column('source_row', sa.Integer(), nullable=True), schema='public')
