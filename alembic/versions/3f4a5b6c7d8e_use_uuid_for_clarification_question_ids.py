"""use uuid for clarification question ids

Revision ID: 3f4a5b6c7d8e
Revises: e0e734257a49
Create Date: 2026-06-12

"""
from typing import Sequence, Union

from alembic import op


revision: str = "3f4a5b6c7d8e"
down_revision: Union[str, Sequence[str], None] = "9c1d2e3f4a5b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE clarification_question_answer_options DROP CONSTRAINT IF EXISTS clarification_question_answer_options_clarification_question_id_fkey")
    op.execute("ALTER TABLE clarification_question_answer_options DROP CONSTRAINT IF EXISTS clarification_question_answer_op_clarification_question_id_fkey")
    op.execute("ALTER TABLE clarification_question_answer_options DROP CONSTRAINT IF EXISTS clarification_answer_options_question_id_fkey")

    op.execute("""
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'clarification_questions'
              AND column_name = 'clarification_question_id'
              AND data_type <> 'uuid'
        ) THEN
            ALTER TABLE clarification_questions
            ALTER COLUMN clarification_question_id TYPE UUID USING clarification_question_id::uuid;
        END IF;
    END $$;
    """)

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

        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'clarification_question_answer_options'
              AND column_name = 'clarification_question_id'
              AND data_type <> 'uuid'
        ) THEN
            ALTER TABLE clarification_question_answer_options
            ALTER COLUMN clarification_question_id TYPE UUID USING clarification_question_id::uuid;
        END IF;
    END $$;
    """)

    op.execute("""
    ALTER TABLE clarification_question_answer_options
    ADD CONSTRAINT clarification_question_answer_options_clarification_question_id_fkey
    FOREIGN KEY (clarification_question_id)
    REFERENCES clarification_questions(clarification_question_id)
    ON DELETE CASCADE
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE clarification_question_answer_options DROP CONSTRAINT IF EXISTS clarification_question_answer_options_clarification_question_id_fkey")

    op.execute("""
    ALTER TABLE clarification_question_answer_options
    ALTER COLUMN clarification_question_id TYPE VARCHAR(255) USING clarification_question_id::text
    """)
    op.execute("""
    ALTER TABLE clarification_question_answer_options
    ALTER COLUMN id TYPE VARCHAR(255) USING id::text
    """)
    op.execute("""
    ALTER TABLE clarification_questions
    ALTER COLUMN clarification_question_id TYPE VARCHAR(255) USING clarification_question_id::text
    """)

    op.execute("""
    ALTER TABLE clarification_question_answer_options
    ADD CONSTRAINT clarification_question_answer_options_clarification_question_id_fkey
    FOREIGN KEY (clarification_question_id)
    REFERENCES clarification_questions(clarification_question_id)
    ON DELETE CASCADE
    """)
