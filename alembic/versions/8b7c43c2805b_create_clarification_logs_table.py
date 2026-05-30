"""create clarification_logs table

Revision ID: 8b7c43c2805b
Revises: 6b1992cb10d1
Create Date: 2026-04-26 07:17:21.963205

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '8b7c43c2805b'
down_revision: Union[str, None] = '6b1992cb10d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_table(
        'clarification_logs',

        sa.Column('id', postgresql.UUID(as_uuid=True),
                  primary_key=True, nullable=False),

        # Session & User Context
        sa.Column('session_id', sa.String(length=255),
                  nullable=False),
        sa.Column('user_id', postgresql.UUID(
            as_uuid=True), nullable=False),
        sa.Column('user_role', sa.String(length=50),
                  nullable=False),

        # Query Content
        sa.Column('original_query', sa.Text(), nullable=False),

        # Ambiguity Detection
        sa.Column('ambiguity_score', sa.Numeric(
            precision=3, scale=2), nullable=False),
        sa.Column('ambiguity_type', sa.String(
            length=50), nullable=False),

        # Decision Tracking
        sa.Column('decision', sa.String(
            length=10), nullable=False),
        sa.Column('decision_source', sa.String(
            length=20), nullable=False),

        # Clarification Data
        sa.Column('clarifying_question', sa.Text(), nullable=True),
        sa.Column('clarification_answer', sa.Text(), nullable=True),
        sa.Column('disambiguated_query', sa.Text(), nullable=True),

        # User Feedback
        sa.Column('user_feedback', sa.Boolean(), nullable=True),
        sa.Column('needed_correction', sa.Boolean(), nullable=True),

        # Timestamp
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )

    # Indexes
    op.create_index('ix_clarification_logs_session_id',
                    'clarification_logs', ['session_id'])
    op.create_index('ix_clarification_logs_user_id',
                    'clarification_logs', ['user_id'])


def downgrade():
    op.drop_index('ix_clarification_logs_user_id',
                  table_name='clarification_logs')
    op.drop_index('ix_clarification_logs_session_id',
                  table_name='clarification_logs')
    op.drop_table('clarification_logs')
