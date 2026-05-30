"""change_id_to_uuid_on_password_resets_and_revoked_tokens

Revision ID: a42fff81daea
Revises: b7383c868bf5
Create Date: 2026-05-30 09:11:39.317314

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PGUUID


# revision identifiers, used by Alembic.
revision: str = 'a42fff81daea'
down_revision: Union[str, None] = 'b7383c868bf5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # =========================================================
    # TABLE: password_resets
    # =========================================================

    # 1. Aktifkan ekstensi pgcrypto jika belum aktif (untuk gen_random_uuid)
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')

    # 2. Tambah kolom uuid baru (nullable dulu agar bisa di-populate)
    op.add_column(
        "password_resets",
        sa.Column("id_new", PGUUID(as_uuid=True), nullable=True),
    )

    # 3. Isi kolom uuid baru dengan nilai uuid4 untuk setiap baris yang ada
    op.execute(
        """
        UPDATE password_resets
        SET id_new = gen_random_uuid()
        """
    )

    # 4. Drop primary key constraint lama
    op.drop_constraint("password_resets_pkey", "password_resets", type_="primary")

    # 5. Drop kolom id lama (INTEGER)
    op.drop_column("password_resets", "id")

    # 6. Rename kolom baru menjadi id
    op.alter_column("password_resets", "id_new", new_column_name="id", nullable=False)

    # 7. Buat primary key baru pada kolom id (UUID)
    op.create_primary_key("password_resets_pkey", "password_resets", ["id"])

    # 8. Set default server-side untuk kolom id
    op.execute(
        """
        ALTER TABLE password_resets
            ALTER COLUMN id SET DEFAULT gen_random_uuid()
        """
    )

    # =========================================================
    # TABLE: revoked_tokens
    # =========================================================

    # 1. Tambah kolom uuid baru (nullable dulu agar bisa di-populate)
    op.add_column(
        "revoked_tokens",
        sa.Column("id_new", PGUUID(as_uuid=True), nullable=True),
    )

    # 2. Isi kolom uuid baru dengan nilai uuid4 untuk setiap baris yang ada
    op.execute(
        """
        UPDATE revoked_tokens
        SET id_new = gen_random_uuid()
        """
    )

    # 3. Drop primary key constraint lama
    op.drop_constraint("revoked_tokens_pkey", "revoked_tokens", type_="primary")

    # 4. Drop kolom id lama (INTEGER)
    op.drop_column("revoked_tokens", "id")

    # 5. Rename kolom baru menjadi id
    op.alter_column("revoked_tokens", "id_new", new_column_name="id", nullable=False)

    # 6. Buat primary key baru pada kolom id (UUID)
    op.create_primary_key("revoked_tokens_pkey", "revoked_tokens", ["id"])

    # 7. Set default server-side untuk kolom id
    op.execute(
        """
        ALTER TABLE revoked_tokens
            ALTER COLUMN id SET DEFAULT gen_random_uuid()
        """
    )


def downgrade() -> None:
    # =========================================================
    # PERINGATAN: Downgrade akan menghapus data UUID yang ada
    # dan menggantinya dengan integer auto-increment baru.
    # Data relasi yang bergantung pada UUID akan hilang.
    # =========================================================

    # =========================================================
    # TABLE: password_resets
    # =========================================================

    op.add_column(
        "password_resets",
        sa.Column("id_old", sa.Integer(), nullable=True),
    )
    op.execute("CREATE SEQUENCE IF NOT EXISTS password_resets_id_seq")
    op.execute(
        """
        UPDATE password_resets
        SET id_old = nextval('password_resets_id_seq')
        """
    )
    op.drop_constraint("password_resets_pkey", "password_resets", type_="primary")
    op.drop_column("password_resets", "id")
    op.alter_column("password_resets", "id_old", new_column_name="id", nullable=False)
    op.execute(
        """
        ALTER TABLE password_resets
            ALTER COLUMN id SET DEFAULT nextval('password_resets_id_seq')
        """
    )
    op.create_primary_key("password_resets_pkey", "password_resets", ["id"])

    # =========================================================
    # TABLE: revoked_tokens
    # =========================================================

    op.add_column(
        "revoked_tokens",
        sa.Column("id_old", sa.Integer(), nullable=True),
    )
    op.execute("CREATE SEQUENCE IF NOT EXISTS revoked_tokens_id_seq")
    op.execute(
        """
        UPDATE revoked_tokens
        SET id_old = nextval('revoked_tokens_id_seq')
        """
    )
    op.drop_constraint("revoked_tokens_pkey", "revoked_tokens", type_="primary")
    op.drop_column("revoked_tokens", "id")
    op.alter_column("revoked_tokens", "id_old", new_column_name="id", nullable=False)
    op.execute(
        """
        ALTER TABLE revoked_tokens
            ALTER COLUMN id SET DEFAULT nextval('revoked_tokens_id_seq')
        """
    )
    op.create_primary_key("revoked_tokens_pkey", "revoked_tokens", ["id"])
