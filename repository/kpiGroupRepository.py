"""
repository/kpiGroupRepository.py

Handles KPIGroup persistence — auto-created alongside KPI Master/Tracker ingestion.

Desain get_or_create:
  Dipanggil sebelum upsert KPI Master/Tracker. Jika sheet sudah pernah di-ingest,
  grup yang ada akan diupdate (sheet_url, sheet_name bisa berubah).
  Conflict key: (sheet_id, group_type) → UniqueConstraint di model.

Tambahan:
  update()  — partial update berdasarkan dict field yang diberikan.
  delete()  — hard delete; soft-delete tidak didukung karena model tidak
              memiliki kolom `deleted_at` / `is_active`.
"""

import math
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, func, delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from model.KPIGroup import KPIGroupORM
from model.KPIMaster import KPIMasterORM
from model.KPITracker import KPITrackerORM


class KPIGroupRepository:

    def __init__(self, db: AsyncSession):
        self.db = db

    # ─── Get or Create (upsert) ───────────────────────────────────────────────

    async def get_active_scheduled_tracker(self) -> list[KPIGroupORM]:
        """Ambil semua KPI Group type=tracker yang aktif (untuk scheduler dan batch)."""
        result = await self.db.execute(
            select(KPIGroupORM)
            .where(KPIGroupORM.group_type == "tracker")
            .where(KPIGroupORM.is_active == True)
            .order_by(KPIGroupORM.created_at)
        )
        return list(result.scalars().all())

    async def get_or_create(
        self,
        sheet_id:   str,
        group_type: str,
        sheet_url:  str,
        sheet_name: str | None,
        nama_grup:  str,
        tahun:      int | None = None,
        is_active:  bool = True,
    ) -> KPIGroupORM:
        """
        Upsert KPIGroup by (sheet_id, group_type).

        Mengapa upsert dan bukan insert-if-not-exists?
          Sheet yang sama bisa di-ingest ulang (sheet_url berubah jika
          dipindah folder, sheet_name bisa di-rename). Upsert memastikan
          data grup selalu sinkron dengan kondisi terbaru sheet.

        Returns:
            KPIGroupORM — grup yang sudah ada atau baru dibuat.
        """
        try:
            update_set = {
                "sheet_url":  sheet_url,
                "sheet_name": sheet_name,
                "nama_grup":  nama_grup,
                "updated_at": func.now(),
                # tahun diupdate jika caller mengirimkan nilai eksplisit
                # agar grup lama dengan tahun NULL bisa terisi saat re-ingest.
            }
            if tahun is not None:
                update_set["tahun"] = tahun

            stmt = (
                insert(KPIGroupORM)
                .values(
                    sheet_id=sheet_id,
                    group_type=group_type,
                    sheet_url=sheet_url,
                    sheet_name=sheet_name,
                    nama_grup=nama_grup,
                    tahun=tahun,
                    is_active=is_active,
                )
                .on_conflict_do_update(
                    constraint="uq_kpigroup_sheet_type",
                    set_=update_set,
                )
                .returning(KPIGroupORM.id)
            )

            result = await self.db.execute(stmt)
            group_id = result.scalar_one()
            await self.db.flush()

            group = await self.db.get(KPIGroupORM, group_id)
            return group

        except Exception as e:
            await self.db.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"Gagal buat/update KPI Group: {str(e)}",
            )

    # ─── Read ─────────────────────────────────────────────────────────────────

    async def get_by_id(self, group_id: UUID) -> KPIGroupORM | None:
        """
        Fetch KPIGroup beserta relasi yang relevan berdasarkan group_type.

        Alur dua langkah:
          Query 1 — fetch grup tanpa relationship (metadata saja).
          Query 2 — db.refresh() hanya relasi yang sesuai group_type:
                      'master'  → master_records  (list[KPIMasterORM])
                      'tracker' → tracker_records (list[KPITrackerORM])

        Returns:
            KPIGroupORM dengan relasi ter-load, atau None jika tidak ada.
        """
        # ── Query 1: ambil metadata grup (ringan, tanpa relationship) ─────────
        result = await self.db.execute(
            select(KPIGroupORM).where(KPIGroupORM.id == group_id)
        )
        group = result.scalars().first()

        if not group:
            return None

        # ── Query 2: load HANYA relasi yang relevan ───────────────────────────
        if group.group_type == "master":
            # master_records ter-load; tracker_records tetap unloaded
            await self.db.refresh(group, attribute_names=["master_records"])

        elif group.group_type == "tracker":
            # tracker_records ter-load; master_records tetap unloaded
            await self.db.refresh(group, attribute_names=["tracker_records"])

        return group

    async def get_master_groups(
        self, page: int = 1, limit: int = 100
    ) -> list[KPIGroupORM]:
        """Ambil semua grup bertipe 'master', diurutkan dari terbaru."""
        offset = (page - 1) * limit
        result = await self.db.execute(
            select(KPIGroupORM)
            .where(KPIGroupORM.group_type == "master")
            .order_by(KPIGroupORM.updated_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return result.scalars().all()

    async def list_groups(
        self,
        page:       int,
        limit:  int,
        tahun:      int | None = None,
        group_type: str | None = None,
        search:     str | None = None,
    ) -> tuple[list[KPIGroupORM], int]:
        """
        List KPI Groups dengan pagination, filter tipe/tahun, dan pencarian nama grup.

        Returns:
            (rows, total_count)
        """
        base_query = select(KPIGroupORM)

        if group_type:
            base_query = base_query.where(KPIGroupORM.group_type == group_type)

        if tahun is not None:
            base_query = base_query.where(KPIGroupORM.tahun == tahun)

        if search:
            pattern = f"%{search}%"
            base_query = base_query.where(KPIGroupORM.nama_grup.ilike(pattern))

        # Hitung total sebelum pagination
        count_result = await self.db.execute(
            select(func.count()).select_from(base_query.subquery())
        )
        total = count_result.scalar_one()

        # Ambil halaman
        offset = (page - 1) * limit
        rows_result = await self.db.execute(
            base_query
            .order_by(KPIGroupORM.updated_at.desc())
            .offset(offset)
            .limit(limit)
        )
        rows = rows_result.scalars().all()

        return rows, total

    # ─── Update ───────────────────────────────────────────────────────────────

    async def update(
        self,
        group_id: UUID,
        fields:   dict,
    ) -> KPIGroupORM:
        """
        Partial update KPIGroup berdasarkan dict `fields` yang diberikan.

        Hanya kolom yang ada dalam `fields` yang akan diupdate —
        kolom lain tidak tersentuh. `updated_at` diupdate otomatis
        oleh `onupdate` di model.

        Args:
            group_id: UUID grup yang akan diupdate.
            fields:   Dict berisi kolom → nilai baru. Kolom yang tidak
                      ada dalam dict tidak akan diubah.

        Returns:
            KPIGroupORM yang sudah diupdate.

        Raises:
            HTTPException 404 jika grup tidak ditemukan.
            HTTPException 500 jika terjadi error database.
        """
        group = await self.get_by_id(group_id)
        if not group:
            raise HTTPException(
                status_code=404,
                detail=f"KPI Group dengan id '{group_id}' tidak ditemukan.",
            )

        try:
            for column, value in fields.items():
                if hasattr(group, column):
                    setattr(group, column, value)

            await self.db.flush()
            await self.db.refresh(group)
            return group

        except Exception as e:
            await self.db.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"Gagal update KPI Group: {str(e)}",
            )

    # ─── Delete ───────────────────────────────────────────────────────────────

    async def delete(self, group_id: UUID) -> None:
        """
        Hard delete KPIGroup beserta seluruh master_records dan tracker_records
        yang berelasi (cascade="all, delete-orphan" sudah dikonfigurasi di model).

        Catatan desain:
          Soft-delete tidak diimplementasikan karena model KPIGroupORM tidak
          memiliki kolom `deleted_at` atau `is_active`. Jika soft-delete
          dibutuhkan di masa depan, tambahkan kolom tersebut ke model dan
          buat migrasi Alembic.

        Args:
            group_id: UUID grup yang akan dihapus.

        Raises:
            HTTPException 404 jika grup tidak ditemukan.
            HTTPException 500 jika terjadi error database.
        """
        group = await self.get_by_id(group_id)
        if not group:
            raise HTTPException(
                status_code=404,
                detail=f"KPI Group dengan id '{group_id}' tidak ditemukan.",
            )

        try:
            await self.db.delete(group)
            await self.db.flush()

        except Exception as e:
            await self.db.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"Gagal hapus KPI Group: {str(e)}",
            )
