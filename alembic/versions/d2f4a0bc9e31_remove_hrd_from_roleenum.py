"""remove hrd from roleenum

Revision ID: d2f4a0bc9e31
Revises: 8b7c43c2805b
Create Date: 2026-04-29 12:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "d2f4a0bc9e31"
down_revision: Union[str, None] = "8b7c43c2805b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_UPGRADE_CHECK = "role IN ('admin', 'kepala_divisi', 'karyawan')"
_DOWNGRADE_CHECK = "role IN ('admin', 'hrd', 'kepala_divisi', 'karyawan')"


def _has_native_roleenum(bind) -> bool:
    return bool(
        bind.execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'roleenum')"
            )
        ).scalar()
    )


def _drop_role_check_constraints(bind) -> None:
    inspector = inspect(bind)
    for constraint in inspector.get_check_constraints("users"):
        name = constraint.get("name")
        sqltext = (constraint.get("sqltext") or "").lower()
        if not name:
            continue
        if (
            "role" in sqltext
            and "admin" in sqltext
            and "kepala_divisi" in sqltext
            and "karyawan" in sqltext
        ):
            op.drop_constraint(name, "users", type_="check")


def upgrade() -> None:
    bind = op.get_bind()

    op.execute(
        sa.text(
            "UPDATE users SET role = 'kepala_divisi' WHERE role = 'hrd'"
        )
    )

    if _has_native_roleenum(bind):
        op.execute("ALTER TABLE users ALTER COLUMN role TYPE text USING role::text")
        op.execute("DROP TYPE roleenum")
        op.execute("CREATE TYPE roleenum AS ENUM ('admin', 'kepala_divisi', 'karyawan')")
        op.execute("ALTER TABLE users ALTER COLUMN role TYPE roleenum USING role::roleenum")
        return

    _drop_role_check_constraints(bind)
    op.create_check_constraint(
        constraint_name="roleenum",
        table_name="users",
        condition=_UPGRADE_CHECK,
    )


def downgrade() -> None:
    bind = op.get_bind()

    if _has_native_roleenum(bind):
        op.execute("ALTER TABLE users ALTER COLUMN role TYPE text USING role::text")
        op.execute("DROP TYPE roleenum")
        op.execute(
            "CREATE TYPE roleenum AS ENUM ('admin', 'hrd', 'kepala_divisi', 'karyawan')"
        )
        op.execute("ALTER TABLE users ALTER COLUMN role TYPE roleenum USING role::roleenum")
        return

    _drop_role_check_constraints(bind)
    op.create_check_constraint(
        constraint_name="roleenum",
        table_name="users",
        condition=_DOWNGRADE_CHECK,
    )
