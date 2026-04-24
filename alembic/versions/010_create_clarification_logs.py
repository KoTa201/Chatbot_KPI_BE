"""Create clarification_logs table for clarification mechanism tracking

Revision ID: 010_create_clarification_logs
Revises: 009_create_ingestion_logs
Create Date: 2026-04-18 02:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "010_create_clarification_logs"
down_revision: Union[str, None] = "009_create_ingestion_logs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "clarification_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", sa.String(length=255), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_role", sa.String(length=50), nullable=False),
        sa.Column("original_query", sa.Text(), nullable=False),
        sa.Column("ambiguity_score", sa.Numeric(precision=3, scale=2), nullable=False),
        sa.Column("ambiguity_type", sa.String(length=50), nullable=False),
        sa.Column("decision", sa.String(length=10), nullable=False),
        sa.Column("decision_source", sa.String(length=20), nullable=False),
        sa.Column("clarifying_question", sa.Text(), nullable=True),
        sa.Column("clarification_answer", sa.Text(), nullable=True),
        sa.Column("disambiguated_query", sa.Text(), nullable=True),
        sa.Column("user_feedback", sa.Boolean(), nullable=True),
        sa.Column("needed_correction", sa.Boolean(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_clarification_session_id",
        "clarification_logs",
        ["session_id"],
        unique=False,
    )
    op.create_index(
        "ix_clarification_user_id",
        "clarification_logs",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_clarification_user_id", table_name="clarification_logs")
    op.drop_index("ix_clarification_session_id", table_name="clarification_logs")
    op.drop_table("clarification_logs")
