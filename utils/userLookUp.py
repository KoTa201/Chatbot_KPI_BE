"""
utils/userLookupUtil.py
Utilitas resolusi nama/email → user_id untuk dipakai oleh ingestion services.

Desain:
  - Satu class (UserLookupUtil) per request / per session.
  - Cache in-memory selama lifetime object: hindari N+1 query ke tabel users
    saat memproses ratusan/ribuan baris sheet sekaligus.
  - Matching case-insensitive + strip whitespace.
  - Behavior saat tidak ditemukan: kembalikan None (nullable FK).
    Caller yang menentukan apakah None diterima atau dianggap error.

Contoh pemakaian:
    lookup = UserLookupUtil(db)
    await lookup.preload()                       # opsional, cache semua user

    user_id = await lookup.by_full_name("Budi Santoso")   # → UUID | None
    user_id = await lookup.by_email("budi@company.com")   # → UUID | None
    user_id = await lookup.by_username("budi")             # → UUID | None
"""

from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from model.User import User

logger = logging.getLogger(__name__)


class UserLookupUtil:
    """
    Resolver nama/email/username → UUID user, dengan cache per instance.

    Thread-safety: tidak thread-safe. Buat satu instance per request.
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        # Cache: key = (strategy, normalized_value), value = UUID | None
        self._cache: dict[tuple[str, str], Optional[UUID]] = {}
        self._preloaded = False

    # ──────────────────────────────────────────────────────────── #
    #  Public API                                                   #
    # ──────────────────────────────────────────────────────────── #

    async def preload(self) -> None:
        """
        Muat semua user ke cache sekaligus.
        Sangat direkomendasikan sebelum memproses banyak baris,
        karena mengganti N query SELECT menjadi 1.
        """
        result = await self._db.execute(
            select(User.id, User.full_name, User.email, User.username)
        )
        rows = result.fetchall()

        for row in rows:
            uid: UUID = row.id
            if row.full_name:
                self._cache[("full_name", _normalize(row.full_name))] = uid
            if row.email:
                self._cache[("email", _normalize(row.email))] = uid
            if row.username:
                self._cache[("username", _normalize(row.username))] = uid

        self._preloaded = True
        logger.debug("[UserLookup] Preloaded %s users into cache.", len(rows))

    async def by_full_name(self, name: str | None) -> Optional[UUID]:
        """
        Cari user berdasarkan full_name (case-insensitive, strip whitespace).
        Jika ada lebih dari satu user dengan nama sama → ambil yang pertama
        ditemukan dan log WARNING.
        """
        if not name or not name.strip():
            return None
        return await self._lookup("full_name", name, User.full_name)

    async def by_email(self, email: str | None) -> Optional[UUID]:
        """Cari user berdasarkan email (case-insensitive)."""
        if not email or not email.strip():
            return None
        return await self._lookup("email", email, User.email)

    async def by_username(self, username: str | None) -> Optional[UUID]:
        """Cari user berdasarkan username (case-insensitive)."""
        if not username or not username.strip():
            return None
        return await self._lookup("username", username, User.username)

    async def by_first_name_in_text(self, text: str | None) -> Optional[UUID]:
        """
        Ambil nama pertama dari teks comma-separated, lalu cari berdasarkan full_name.
        Berguna untuk memigrasi field responsibility_persons (master KPI).

        Contoh: "Budi Santoso, Ani Wati" → cari "Budi Santoso"
        """
        if not text or not text.strip():
            return None
        first_name = text.split(",")[0].strip()
        return await self.by_full_name(first_name)

    def stats(self) -> dict:
        """Kembalikan statistik cache untuk debugging/logging."""
        return {
            "preloaded": self._preloaded,
            "cache_entries": len(self._cache),
        }

    # ──────────────────────────────────────────────────────────── #
    #  Internal                                                     #
    # ──────────────────────────────────────────────────────────── #

    async def _lookup(self, strategy: str, value: str, column) -> Optional[UUID]:
        key = (strategy, _normalize(value))

        if key in self._cache:
            return self._cache[key]

        # Cache miss: query ke DB
        result = await self._db.execute(
            select(User.id).where(
                # Gunakan ilike untuk case-insensitive di PostgreSQL
                column.ilike(_normalize(value))
            )
        )
        rows = result.fetchall()

        if not rows:
            logger.debug(
                "[UserLookup] No user found for %s=%r", strategy, value
            )
            uid = None
        else:
            if len(rows) > 1:
                logger.warning(
                    "[UserLookup] Ambiguous match: %s user(s) found for %s=%r. "
                    "Menggunakan yang pertama.",
                    len(rows),
                    strategy,
                    value,
                )
            uid = rows[0].id

        self._cache[key] = uid
        return uid


# ──────────────────────────────────────────────────────────────── #
#  Standalone helper (tanpa cache, cocok untuk satu-kali lookup)   #
# ──────────────────────────────────────────────────────────────── #

async def resolve_user_id_by_name(
    db: AsyncSession,
    name: str | None,
) -> Optional[UUID]:
    """
    One-shot lookup user_id berdasarkan full_name.
    Tidak ada cache — gunakan UserLookupUtil.preload() untuk batch processing.
    """
    if not name or not name.strip():
        return None

    result = await db.execute(
        select(User.id).where(User.full_name.ilike(_normalize(name))).limit(1)
    )
    uid = result.scalar_one_or_none()
    if uid is None:
        logger.debug("[UserLookup] User not found for name=%r", name)
    return uid


def _normalize(value: str) -> str:
    """Lowercase + strip whitespace untuk perbandingan konsisten."""
    return value.strip().lower()