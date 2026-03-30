"""
repository/authRepository.py
Semua operasi CRUD ke tabel users.
Tidak ada logika bisnis di sini — hanya interaksi langsung dengan ORM.
"""

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from model import UserORM


class AuthRepository:

    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------ #
    #  Create                                                              #
    # ------------------------------------------------------------------ #

    async def create_user(self, user: UserORM) -> UserORM:
        """Insert user baru. Kembalikan instance yang sudah ter-refresh (id terisi)."""
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    # ------------------------------------------------------------------ #
    #  Read                                                                #
    # ------------------------------------------------------------------ #

    async def get_by_id(self, user_id: int) -> Optional[UserORM]:
        """Cari user berdasarkan primary key. Return None jika tidak ada."""
        result = await self.db.execute(
            select(UserORM).where(UserORM.id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_by_username_or_email(self, identifier: str) -> Optional[UserORM]:
        """
        Cari user berdasarkan username atau email dalam satu query.
        Deteksi otomatis: jika identifier mengandung '@' diperlakukan sebagai email,
        selain itu sebagai username.
        """
        if "@" in identifier:
            result = await self.db.execute(
                select(UserORM).where(UserORM.email == identifier)
            )
        else:
            result = await self.db.execute(
                select(UserORM).where(UserORM.username == identifier)
            )
        return result.scalar_one_or_none()

    async def get_by_username(self, username: str) -> Optional[UserORM]:
        """Cari user berdasarkan username (case-sensitive). Return None jika tidak ada."""
        result = await self.db.execute(
            select(UserORM).where(UserORM.username == username)
        )
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> Optional[UserORM]:
        """Cari user berdasarkan email. Return None jika tidak ada."""
        result = await self.db.execute(
            select(UserORM).where(UserORM.email == email)
        )
        return result.scalar_one_or_none()

    async def get_all_users(
        self,
        limit: int = 20,
        offset: int = 0,
    ) -> list[UserORM]:
        """Ambil semua user dengan pagination, diurutkan dari terbaru."""
        result = await self.db.execute(
            select(UserORM)
            .order_by(UserORM.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all()

    async def count_all_users(self) -> int:
        """Hitung total seluruh user (untuk keperluan pagination)."""
        from sqlalchemy import func
        result = await self.db.execute(select(func.count()).select_from(UserORM))
        return result.scalar_one()

    # ------------------------------------------------------------------ #
    #  Update                                                              #
    # ------------------------------------------------------------------ #

    async def save(self, user: UserORM) -> UserORM:
        """
        Simpan perubahan pada instance ORM yang sudah di-mutasi.
        Digunakan untuk update maupun soft-delete (is_active=False).
        """
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    # ------------------------------------------------------------------ #
    #  Delete                                                              #
    # ------------------------------------------------------------------ #

    async def delete_user(self, user: UserORM) -> None:
        """Hard-delete user dari database."""
        await self.db.delete(user)
        await self.db.commit()

    # ------------------------------------------------------------------ #
    #  Existence checks                                                    #
    # ------------------------------------------------------------------ #

    async def username_exists(self, username: str) -> bool:
        result = await self.db.execute(
            select(UserORM.id).where(UserORM.username == username)
        )
        return result.scalar_one_or_none() is not None

    async def email_exists(self, email: str) -> bool:
        result = await self.db.execute(
            select(UserORM.id).where(UserORM.email == email)
        )
        return result.scalar_one_or_none() is not None
