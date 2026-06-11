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

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from model.KPIGroup import KPIGroup
from model.KPIMaster import KPIMaster
from model.KPITracker import KPITracker
from sqlalchemy.orm import selectinload


class KPIGroupRepository:

    def __init__(self, db: AsyncSession):
        self.db: AsyncSession = db

    # ─── Get or Create (upsert) ───────────────────────────────────────────────

    async def get_active_scheduled_tracker(self) -> list[KPIGroup]:
        """Ambil semua KPI Group type=tracker yang aktif (untuk scheduler dan batch)."""
        result = await self.db.execute(
            select(KPIGroup)
            .where(KPIGroup.group_type == "tracker")
            .where(KPIGroup.is_active == True)
            .order_by(KPIGroup.created_at)
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
    ) -> KPIGroup:
        """
        Upsert KPIGroup by (sheet_id, group_type).

        Mengapa upsert dan bukan insert-if-not-exists?
          Sheet yang sama bisa di-ingest ulang (sheet_url berubah jika
          dipindah folder, sheet_name bisa di-rename). Upsert memastikan
          data grup selalu sinkron dengan kondisi terbaru sheet.

        Returns:
            KPIGroup — grup yang sudah ada atau baru dibuat.
        """
        try:
            update_set = {
                "sheet_url":  sheet_url,
                "sheet_name": sheet_name,
                "nama_grup":  nama_grup,
                "updated_at": func.now(),
            }
            if tahun is not None:
                # pyrefly: ignore [bad-typed-dict-key]
                update_set["tahun"] = tahun

            stmt = (
                insert(KPIGroup)
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
                .returning(KPIGroup.id)
            )

            result = await self.db.execute(stmt)
            group_id = result.scalar_one()
            await self.db.flush()

            group = await self.db.get(KPIGroup, group_id)
            if not group:
                raise HTTPException(
                    status_code=500,
                    detail="Gagal retrieve KPI Group setelah upsert.",
                )
            return group

        except HTTPException:
            raise
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"Gagal buat/update KPI Group: {str(e)}",
            )

    async def get_or_create_committed(
        self,
        sheet_id: str,
        group_type: str,
        sheet_url: str,
        sheet_name: str | None,
        nama_grup: str,
        tahun: int | None = None,
        is_active: bool = True,
    ) -> KPIGroup:
        group = await self.get_or_create(
            sheet_id=sheet_id,
            group_type=group_type,
            sheet_url=sheet_url,
            sheet_name=sheet_name,
            nama_grup=nama_grup,
            tahun=tahun,
            is_active=is_active,
        )
        await self.db.commit()
        await self.db.refresh(group)
        return group

    # ─── Read ─────────────────────────────────────────────────────────────────

    async def get_by_id(self, group_id: UUID) -> KPIGroup | None:
        """
        Fetch KPIGroup beserta relasi yang relevan berdasarkan group_type.

        Alur dua langkah:
        Query 1 — fetch grup tanpa relationship (metadata saja).
        Query 2 — re-query dengan selectinload hanya relasi yang sesuai group_type:
                    'master'  → master_records + pic_users (M2M via kpi_master_users)
                    'tracker' → tracker_records + user     (FK langsung via user_id)

        Returns:
            KPIGroup dengan relasi ter-load, atau None jika tidak ada.
        """
        # ── Query 1: ambil metadata grup (ringan, tanpa relationship) ─────────
        result = await self.db.execute(
            select(KPIGroup).where(KPIGroup.id == group_id)
        )
        group = result.scalars().first()

        if not group:
            return None

        # ── Query 2: load HANYA relasi yang relevan ───────────────────────────
        if group.group_type == "master":
            # master_records ter-load beserta pic_users tiap record
            # (M2M: kpi_master_records → kpi_master_users → users)
            result = await self.db.execute(
                select(KPIGroup)
                .where(KPIGroup.id == group_id)
                .options(
                    selectinload(KPIGroup.master_records).selectinload(KPIMaster.pic_users)
                )
            )
            group = result.scalars().first()

        elif group.group_type == "tracker":
            # tracker_records ter-load beserta user tiap record
            # (FK langsung: kpi_tracker_records.user_id → users.id)
            result = await self.db.execute(
                select(KPIGroup)
                .where(KPIGroup.id == group_id)
                .options(
                    selectinload(KPIGroup.tracker_records).selectinload(KPITracker.user)
                )
            )
            group = result.scalars().first()

        return group

    async def get_master_groups(
        self, page: int = 1, limit: int = 100
    ) -> list[KPIGroup]:
        """Ambil semua grup bertipe 'master', diurutkan dari terbaru."""
        offset = (page - 1) * limit
        result = await self.db.execute(
            select(KPIGroup)
            .where(KPIGroup.group_type == "master")
            .order_by(KPIGroup.updated_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_groups(
        self,
        page:       int,
        limit:  int,
        tahun:      int | None = None,
        group_type: str | None = None,
        search:     str | None = None,
    ) -> tuple[list[KPIGroup], int]:
        """
        List KPI Groups dengan pagination, filter tipe/tahun, dan pencarian nama grup.

        Returns:
            (rows, total_count)
        """
        base_query = select(KPIGroup)

        if group_type:
            base_query = base_query.where(KPIGroup.group_type == group_type)

        if tahun is not None:
            base_query = base_query.where(KPIGroup.tahun == tahun)

        if search:
            pattern = f"%{search}%"
            base_query = base_query.where(KPIGroup.nama_grup.ilike(pattern))

        # Hitung total sebelum pagination
        count_result = await self.db.execute(
            select(func.count()).select_from(base_query.subquery())
        )
        total = count_result.scalar_one()

        # Ambil halaman
        offset = (page - 1) * limit
        rows_result = await self.db.execute(
            base_query
            .order_by(KPIGroup.updated_at.desc())
            .offset(offset)
            .limit(limit)
        )
        rows = list(rows_result.scalars().all())

        return rows, total

    # ─── Update ───────────────────────────────────────────────────────────────

    async def update(
        self,
        group_id: UUID,
        fields: dict,
    ) -> KPIGroup:
        try:
            # Fetch dulu dari DB agar object terhubung ke session
            result = await self.db.execute(
                select(KPIGroup).where(KPIGroup.id == group_id)
            )
            group = result.scalar_one_or_none()

            if not group:
                raise HTTPException(
                    status_code=404,
                    detail=f"KPI Group dengan id '{group_id}' tidak ditemukan.",
                )

            for column, value in fields.items():
                if hasattr(group, column):
                    setattr(group, column, value)

            await self.db.flush()
            await self.db.refresh(group)
            return group

        except HTTPException:
            raise
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"Gagal update KPI Group: {str(e)}",
            )

    async def update_committed(
        self,
        group_id: UUID,
        fields: dict,
    ) -> KPIGroup:
        group = await self.update(group_id=group_id, fields=fields)
        await self.db.commit()
        await self.db.refresh(group)
        return group

    # ─── Delete ───────────────────────────────────────────────────────────────

    async def delete(self, group_id: UUID) -> None:
        """
        Hard delete KPIGroup beserta seluruh master_records dan tracker_records
        yang berelasi (cascade="all, delete-orphan" sudah dikonfigurasi di model).

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

    async def delete_committed(self, group_id: UUID) -> None:
        await self.delete(group_id)
        await self.db.commit()
