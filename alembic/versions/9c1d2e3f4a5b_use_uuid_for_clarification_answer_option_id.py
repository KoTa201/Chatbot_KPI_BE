"""use uuid for clarification answer option id

Revision ID: 9c1d2e3f4a5b
Revises: e0e734257a49
Create Date: 2026-06-12

"""
from typing import Sequence, Union

from alembic import op


revision: str = "9c1d2e3f4a5b"
down_revision: Union[str, Sequence[str], None] = "e0e734257a49"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'clarification_question_answer_options'
              AND column_name = 'id'
              AND data_type <> 'uuid'
        ) THEN
            ALTER TABLE clarification_question_answer_options
            ALTER COLUMN id TYPE UUID USING id::uuid;
        END IF;
    END $$;
    """)


def downgrade() -> None:
    op.execute("""
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'clarification_question_answer_options'
              AND column_name = 'id'
              AND data_type = 'uuid'
        ) THEN
            ALTER TABLE clarification_question_answer_options
            ALTER COLUMN id TYPE VARCHAR(255) USING id::text;
        END IF;
    END $$;
    """)
