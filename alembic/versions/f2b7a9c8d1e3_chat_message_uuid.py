"""convert chat message ids to uuid

Revision ID: f2b7a9c8d1e3
Revises: c3a71be44b6d
Create Date: 2026-05-29 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "f2b7a9c8d1e3"
down_revision: Union[str, None] = "c3a71be44b6d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE clarification_questions "
        "DROP CONSTRAINT IF EXISTS clarification_questions_message_id_fkey"
    )
    op.execute(
        "ALTER TABLE chat_messages ALTER COLUMN message_id TYPE UUID USING message_id::uuid"
    )
    op.execute(
        "ALTER TABLE clarification_questions ALTER COLUMN message_id TYPE UUID USING message_id::uuid"
    )
    op.execute(
        "ALTER TABLE clarification_questions ADD CONSTRAINT clarification_questions_message_id_fkey "
        "FOREIGN KEY (message_id) REFERENCES chat_messages(message_id) ON DELETE CASCADE"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE clarification_questions "
        "DROP CONSTRAINT IF EXISTS clarification_questions_message_id_fkey"
    )
    op.alter_column(
        "clarification_questions",
        "message_id",
        existing_type=postgresql.UUID(as_uuid=True),
        type_=sa.String(length=255),
        postgresql_using="message_id::text",
        existing_nullable=True,
    )
    op.alter_column(
        "chat_messages",
        "message_id",
        existing_type=postgresql.UUID(as_uuid=True),
        type_=sa.String(length=255),
        postgresql_using="message_id::text",
        existing_nullable=False,
    )
    op.create_foreign_key(
        "clarification_questions_message_id_fkey",
        "clarification_questions",
        "chat_messages",
        ["message_id"],
        ["message_id"],
        ondelete="CASCADE",
    )
