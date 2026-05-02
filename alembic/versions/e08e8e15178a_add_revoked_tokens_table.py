"""add revoked_tokens table

Revision ID: e08e8e15178a
Revises: bbca1d8c04e7
Create Date: 2026-05-02 21:27:04.906559

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e08e8e15178a'
down_revision: Union[str, None] = 'bbca1d8c04e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "revoked_tokens",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("token", sa.String(), nullable=False),
        sa.Column(
            "user_id",
            sa.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "revoked_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
 
    # Index untuk kolom token (unique)
    op.create_index(
        op.f("ix_revoked_tokens_token"),
        "revoked_tokens",
        ["token"],
        unique=True,
    )
 
    # Index untuk kolom user_id
    op.create_index(
        op.f("ix_revoked_tokens_user_id"),
        "revoked_tokens",
        ["user_id"],
        unique=False,
    )
 
 
def downgrade() -> None:
    op.drop_index(op.f("ix_revoked_tokens_user_id"), table_name="revoked_tokens")
    op.drop_index(op.f("ix_revoked_tokens_token"), table_name="revoked_tokens")
    op.drop_table("revoked_tokens")
