"""rename chatbot attributes to english

Revision ID: 8458b8733e3a
Revises: 2fd9c1b7a6e4
Create Date: 2026-05-14 10:17:51.405333

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8458b8733e3a'
down_revision: Union[str, None] = '2fd9c1b7a6e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index(op.f('ix_chatbots_nama_chatbot'), table_name='chatbots')
    op.alter_column('chatbots', 'nama_chatbot', new_column_name='chatbot_name')
    op.alter_column('chatbots', 'otoritas', new_column_name='authority')
    op.create_index(op.f('ix_chatbots_chatbot_name'), 'chatbots', ['chatbot_name'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_chatbots_chatbot_name'), table_name='chatbots')
    op.alter_column('chatbots', 'authority', new_column_name='otoritas')
    op.alter_column('chatbots', 'chatbot_name', new_column_name='nama_chatbot')
    op.create_index(op.f('ix_chatbots_nama_chatbot'), 'chatbots', ['nama_chatbot'], unique=False)
