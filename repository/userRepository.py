"""
repository/authRepository.py
Semua operasi CRUD ke tabel users + revoked token denylist.
Tidak ada logika bisnis di sini — hanya interaksi langsung dengan ORM.
"""

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from model.User import UserORM
from model.RevokedToken import RevokedTokenORM          # ← model baru


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
        result = await self.db.execute(
            select(UserORM).where(UserORM.id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_by_username_or_email(self, identifier: str) -> Optional[UserORM]:
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
        result = await self.db.execute(
            select(UserORM).where(UserORM.username == username)
        )
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> Optional[UserORM]:
        result = await self.db.execute(
            select(UserORM).where(UserORM.email == email)
        )
        return result.scalar_one_or_none()

    async def get_all_users(self, limit: int = 20, offset: int = 0) -> list[UserORM]:
        result = await self.db.execute(
            select(UserORM)
            .order_by(UserORM.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all()

    async def count_all_users(self) -> int:
        from sqlalchemy import func
        result = await self.db.execute(select(func.count()).select_from(UserORM))
        return result.scalar_one()

    # ------------------------------------------------------------------ #
    #  Update                                                              #
    # ------------------------------------------------------------------ #

    async def save(self, user: UserORM) -> UserORM:
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    # ------------------------------------------------------------------ #
    #  Delete                                                              #
    # ------------------------------------------------------------------ #

    async def delete_user(self, user: UserORM) -> None:
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

    # ------------------------------------------------------------------ #
    #  Refresh token denylist                                              #
    # ------------------------------------------------------------------ #

    async def revoke_token(self, token: str) -> None:
        """
        Simpan refresh token ke denylist agar tidak bisa dipakai ulang.
        Dipanggil saat rotate (token lama) maupun logout (token aktif).
        Jika token sudah ada di denylist, operasi diabaikan (idempotent).
        """
        already_revoked = await self.is_token_revoked(token)
        if not already_revoked:
            self.db.add(RevokedTokenORM(token=token))
            await self.db.commit()

    async def is_token_revoked(self, token: str) -> bool:
        """
        Periksa apakah refresh token sudah ada di denylist.
        Return True jika sudah direvoke, False jika masih valid.
        """
        result = await self.db.execute(
            select(RevokedTokenORM.id).where(RevokedTokenORM.token == token)
        )
        return result.scalar_one_or_none() is not None
