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

Changelog:
  v2:
    - Tambah all_ids_in_text(): resolve SEMUA nama comma-separated ke list UUID.
      Mengembalikan (resolved: list[UUID], unresolved: list[str]) agar
      caller bisa tahu nama mana saja yang gagal di-resolve.
      Dipakai untuk relasi many-to-many KPIMaster ↔ User.

Contoh pemakaian:
    lookup = UserLookupUtil(db)
    await lookup.preload()

    # One-to-one (lama)
    user_id = await lookup.by_full_name("Budi Santoso")    # → UUID | None

    # Many-to-many (baru)
    uids, unknown = await lookup.all_ids_in_text("Budi Santoso, Ani Wati")
    # uids    → [UUID(...), UUID(...)]
    # unknown → []  (kosong jika semua resolved)
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

    async def all_ids_in_text(
        self,
        text: str | None,
    ) -> tuple[list[UUID], list[str]]:
        """
        Resolve SEMUA nama dari teks comma-separated ke list UUID.

        Returns:
            resolved   — list UUID yang berhasil di-resolve (urut sesuai input).
            unresolved — list nama yang tidak ditemukan di tabel users.

        Contoh::

            uids, unknown = await lookup.all_ids_in_text("Budi Santoso, Ani Wati, Ghost")
            # uids    → [UUID_budi, UUID_ani]
            # unknown → ["Ghost"]
        """
        if not text or not text.strip():
            return [], []

        names = [n.strip() for n in text.split(",") if n.strip()]
        if not names:
            return [], []

        resolved: list[UUID] = []
        unresolved: list[str] = []
        seen: set[str] = set()

        for name in names:
            # Deduplikasi nama dalam satu field (misal: "Budi, Budi, Ani")
            key = _normalize(name)
            if key in seen:
                continue
            seen.add(key)

            uid = await self.by_full_name(name)
            if uid is not None:
                resolved.append(uid)
            else:
                unresolved.append(name)

        return resolved, unresolved

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


def _normalize(value: str) -> str:
    """Lowercase + strip whitespace untuk perbandingan konsisten."""
    return value.strip().lower()