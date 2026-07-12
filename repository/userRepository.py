"""
repository/UserRepository.py
Semua operasi CRUD ke tabel users + revoked token denylist.
Tidak ada logika bisnis di sini — hanya interaksi langsung dengan ORM.
"""

from typing import Optional
from uuid import UUID

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from model.PasswordReset import PasswordReset

from model.User import RoleEnum, User
from model.RevokedToken import RevokedToken          # ← model baru
from utils.datetime import utc_now


class UserRepository:

    def __init__(self, db: AsyncSession):
        self.db: AsyncSession = db

    # ------------------------------------------------------------------ #
    #  Create                                                              #
    # ------------------------------------------------------------------ #

    async def create_user(self, user: User) -> User | None:
        """Insert user baru. Kembalikan instance yang sudah ter-refresh (id terisi)."""
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    # ------------------------------------------------------------------ #
    #  Read                                                                #
    # ------------------------------------------------------------------ #

    async def get_by_id(self, user_id: UUID) -> Optional[User]:
        result = await self.db.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_by_username_or_email(self, identifier: str) -> Optional[User]:
        if "@" in identifier:
            result = await self.db.execute(
                select(User).where(User.email == identifier)
            )
        else:
            result = await self.db.execute(
                select(User).where(User.username == identifier)
            )
        return result.scalar_one_or_none()

    async def get_by_username(self, username: str) -> Optional[User]:
        result = await self.db.execute(
            select(User).where(User.username == username)
        )
        return result.scalar_one_or_none()

    async def get_all_users(
        self,
        page: int = 1,
        limit: int = 20,
        search: str | None = None,
        role: RoleEnum | None = None,
        status: bool | None = None,
    ) -> list[User]:
        offset = (page - 1) * limit
        query = select(User)
        if search:
            pattern = f"%{search.strip()}%"
            query = query.where(
                or_(
                    User.username.ilike(pattern),
                    User.full_name.ilike(pattern),
                    User.email.ilike(pattern),
                )
            )
        if role is not None:
            query = query.where(User.role == role)
        if status is not None:
            query = query.where(User.is_active == status)

        result = await self.db.execute(
            query
            .order_by(User.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def count_all_users(
        self,
        search: str | None = None,
        role: RoleEnum | None = None,
        status: bool | None = None,
    ) -> int:
        query = select(func.count()).select_from(User)
        if search:
            pattern = f"%{search.strip()}%"
            query = query.where(
                or_(
                    User.username.ilike(pattern),
                    User.full_name.ilike(pattern),
                    User.email.ilike(pattern),
                )
            )
        if role is not None:
            query = query.where(User.role == role)
        if status is not None:
            query = query.where(User.is_active == status)

        result = await self.db.execute(query)
        return result.scalar_one()

    # ------------------------------------------------------------------ #
    #  Update                                                              #
    # ------------------------------------------------------------------ #

    async def save(self, user: User) -> User:
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    # ------------------------------------------------------------------ #
    #  Delete                                                              #
    # ------------------------------------------------------------------ #

    async def delete_user(self, user: User) -> None:
        await self.db.delete(user)
        await self.db.commit()

    # ------------------------------------------------------------------ #
    #  Existence checks                                                    #
    # ------------------------------------------------------------------ #

    async def username_exists(self, username: str) -> bool:
        result = await self.db.execute(
            select(User.id).where(User.username == username)
        )
        return result.scalar_one_or_none() is not None

    async def email_exists(self, email: str) -> bool:
        result = await self.db.execute(
            select(User.id).where(User.email == email)
        )
        return result.scalar_one_or_none() is not None

    # ------------------------------------------------------------------ #
    #  Refresh token denylist                                              #
    # ------------------------------------------------------------------ #

    async def revoke_token(self, token: str, user_id: UUID) -> None:
        """
        Simpan refresh token ke denylist agar tidak bisa dipakai ulang.
        Dipanggil saat rotate (token lama) maupun logout (token aktif).
        Jika token sudah ada di denylist, operasi diabaikan (idempotent).
        """
        already_revoked = await self.is_token_revoked(token)
        if not already_revoked:
            self.db.add(RevokedToken(token=token, user_id=user_id))
            await self.db.commit()

    async def is_token_revoked(self, token: str) -> bool:
        """
        Periksa apakah refresh token sudah ada di denylist.
        Return True jika sudah direvoke, False jika masih valid.
        """
        result = await self.db.execute(
            select(RevokedToken.id).where(RevokedToken.token == token)
        )
        return result.scalar_one_or_none() is not None

    async def get_active_reset_pin(self, user_id: UUID) -> PasswordReset | None:
        """Ambil PIN reset aktif (belum dipakai, belum expired)."""
        now = utc_now()
        result = await self.db.execute(
            select(PasswordReset)
            .where(
                PasswordReset.user_id == user_id,
                PasswordReset.expires_at > now,
                PasswordReset.used_at.is_(None),
            )
            .order_by(PasswordReset.expires_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def create_reset_pin(self, record: PasswordReset) -> PasswordReset:
        """Hapus PIN lama user (jika ada) lalu simpan yang baru."""
        await self.db.execute(
            delete(PasswordReset).where(
                PasswordReset.user_id == record.user_id)
        )
        self.db.add(record)
        await self.db.commit()
        await self.db.refresh(record)
        return record

    async def mark_reset_pin_used(self, record: PasswordReset) -> None:
        """Tandai PIN sebagai sudah dipakai."""
        record.used_at = utc_now()
        await self.db.commit()
