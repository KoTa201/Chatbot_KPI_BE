"""
repository/kpiMasterRepository.py
DB operations for KPI Master — disesuaikan dengan model baru (group_id FK).

Perubahan utama dari versi sebelumnya:
  - Conflict key upsert: (group_id, kpi_name) via constraint "uq_kpimaster_group_name"
    menggantikan (tahun, kpi_name).
  - Kolom source_sheet_id / source_sheet_name DIHAPUS dari _UPSERT_COLS —
    info sheet kini ada di kpi_groups, bukan di setiap baris master.
  - Semua grouped queries di-JOIN ke kpi_groups agar bisa group by sheet info.
  - delete_by_source_sheet_name: resolve group dulu lewat JOIN, baru hapus masters.

Interface publik (nama metode & struktur return) TIDAK BERUBAH
agar controller dan service tidak perlu tahu detail JOIN internal.
"""

from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import desc, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from model.KPIMaster import KPIMasterORM
from model.KPIGroup import KPIGroupORM

# Kolom yang diupdate saat conflict (group_id & kpi_name adalah conflict key, tidak diupdate)
_UPSERT_COLS = [
    "tahun",
    "category",
    "definisi_operasional",
    "target",
    "achieve",
    "partial",
    "fail",
    "responsibility_persons",
]


class KPIMasterRepository:

    def __init__(self, db: AsyncSession):
        self.db = db
        self.kpi_masters:  list[dict] = []
        self.upsert_count: int = 0

    # ================================================================ #
    #  UPSERT                                                           #
    # ================================================================ #

    async def upsert_by_group(self, records: list[dict]) -> int:
        """
        Upsert KPI Master. Conflict on (group_id, kpi_name) → update konten KPI.

        Records HARUS sudah menyertakan 'group_id' (UUID) sebelum dipanggil.
        group_id diisi oleh KPIMasterIngestionService setelah KPIGroup dibuat.

        Returns:
            Jumlah records yang di-upsert.
        """
        if not records:
            self.kpi_masters = []
            self.upsert_count = 0
            return 0

        self.kpi_masters = records

        try:
            stmt = insert(KPIMasterORM).values(records)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_kpimaster_group_name",   # (group_id, kpi_name)
                set_={col: stmt.excluded[col] for col in _UPSERT_COLS},
            )
            await self.db.execute(stmt)
            await self.db.commit()
            self.upsert_count = len(records)
            return self.upsert_count

        except Exception as e:
            await self.db.rollback()
            self.kpi_masters = []
            self.upsert_count = 0
            raise HTTPException(
                status_code=500,
                detail=f"Gagal simpan KPI Master ke database: {str(e)}",
            )

    # Alias untuk backward-compat internal calls (ingestion service lama)
    async def upsert_by_tahun(self, records: list[dict]) -> int:
        return await self.upsert_by_group(records)

    # ================================================================ #
    #  GROUP/AGGREGATE — grouped by source sheet (via kpi_groups JOIN)  #
    # ================================================================ #

    async def get_grouped_by_source_sheet_name(
        self, skip: int = 0, limit: int = 100
    ) -> list[dict]:
        """
        Ambil KPI Masters dikelompokkan per sheet (via JOIN kpi_groups).
        Return shape sama seperti sebelumnya agar service/controller tidak berubah.

        Sebelumnya GROUP BY source_sheet_name (kolom di kpi_master_records).
        Sekarang GROUP BY kpi_groups.id karena info sheet ada di sana.
        """
        try:
            query = (
                select(
                    KPIGroupORM.id.label("group_id"),
                    KPIGroupORM.sheet_name.label("source_sheet_name"),
                    func.count(KPIMasterORM.id).label("total_count"),
                    func.array_agg(
                        KPIMasterORM.tahun, distinct=True
                    ).label("tahun_list"),
                    func.array_agg(
                        KPIMasterORM.category, distinct=True
                    ).label("categories"),
                    func.count(
                        KPIMasterORM.kpi_name, distinct=True
                    ).label("kpi_count"),
                    func.max(KPIMasterORM.created_at).label("last_updated"),
                )
                .join(KPIMasterORM, KPIMasterORM.group_id == KPIGroupORM.id)
                .where(KPIGroupORM.group_type == "master")
                .group_by(KPIGroupORM.id, KPIGroupORM.sheet_name)
                .order_by(desc(func.max(KPIMasterORM.created_at)))
                .offset(skip)
                .limit(limit)
            )

            result = await self.db.execute(query)
            rows = result.fetchall()

            return [
                {
                    "group_id":          str(row.group_id),
                    "source_sheet_name": row.source_sheet_name or "UNKNOWN",
                    "total_count":       row.total_count or 0,
                    "tahun_list":        sorted(list(row.tahun_list)) if row.tahun_list else [],
                    "categories":        sorted(list(row.categories)) if row.categories else [],
                    "kpi_count":         row.kpi_count or 0,
                    "last_updated":      row.last_updated,
                }
                for row in rows
            ]

        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Gagal ambil grouped KPI Masters: {str(e)}",
            )

    async def get_grouped_by_source_sheet_name_with_filters(
        self,
        tahun:    Optional[int] = None,
        category: Optional[str] = None,
        skip:     int = 0,
        limit:    int = 100,
    ) -> list[dict]:
        """
        Grouped query dengan filter tahun/category.
        Filter diterapkan ke kpi_master_records; grouping tetap di kpi_groups level.
        """
        try:
            query = (
                select(
                    KPIGroupORM.id.label("group_id"),
                    KPIGroupORM.sheet_name.label("source_sheet_name"),
                    func.count(KPIMasterORM.id).label("total_count"),
                    func.array_agg(
                        KPIMasterORM.tahun, distinct=True
                    ).label("tahun_list"),
                    func.array_agg(
                        KPIMasterORM.category, distinct=True
                    ).label("categories"),
                    func.count(
                        KPIMasterORM.kpi_name, distinct=True
                    ).label("kpi_count"),
                    func.max(KPIMasterORM.created_at).label("last_updated"),
                )
                .join(KPIMasterORM, KPIMasterORM.group_id == KPIGroupORM.id)
                .where(KPIGroupORM.group_type == "master")
            )

            if tahun:
                query = query.where(KPIMasterORM.tahun == tahun)
            if category:
                query = query.where(
                    KPIMasterORM.category.ilike(f"%{category}%")
                )

            query = (
                query
                .group_by(KPIGroupORM.id, KPIGroupORM.sheet_name)
                .order_by(desc(func.max(KPIMasterORM.created_at)))
                .offset(skip)
                .limit(limit)
            )

            result = await self.db.execute(query)
            rows = result.fetchall()

            return [
                {
                    "group_id":          str(row.group_id),
                    "source_sheet_name": row.source_sheet_name or "UNKNOWN",
                    "total_count":       row.total_count or 0,
                    "tahun_list":        sorted(list(row.tahun_list)) if row.tahun_list else [],
                    "categories":        sorted(list(row.categories)) if row.categories else [],
                    "kpi_count":         row.kpi_count or 0,
                    "last_updated":      row.last_updated,
                }
                for row in rows
            ]

        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Gagal ambil grouped KPI Masters dengan filters: {str(e)}",
            )

    async def get_detail_masters_by_source_sheet_name(
        self,
        source_sheet_name: str,
        skip:  int = 0,
        limit: int = 100,
    ) -> list[KPIMasterORM]:
        """
        Ambil detail masters untuk satu sheet.
        Resolve sheet_name lewat JOIN ke kpi_groups (ilike match).
        """
        try:
            query = (
                select(KPIMasterORM)
                .join(KPIGroupORM, KPIMasterORM.group_id == KPIGroupORM.id)
                .where(
                    KPIGroupORM.sheet_name.ilike(f"%{source_sheet_name}%"),
                    KPIGroupORM.group_type == "master",
                )
                .order_by(desc(KPIMasterORM.created_at))
                .offset(skip)
                .limit(limit)
            )

            result = await self.db.execute(query)
            return result.scalars().all()

        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Gagal ambil detail masters: {str(e)}",
            )

    async def delete_by_source_sheet_name(self, source_sheet_name: str) -> int:
        """
        Hapus semua KPI Master dalam grup yang sheet_name-nya cocok.

        Alur:
          1. Temukan grup via kpi_groups.sheet_name (ilike)
          2. Hapus semua KPI Master dalam grup tersebut
             (bukan hapus grupnya — grup mungkin masih dibutuhkan untuk tracker)

        Returns:
            Jumlah records yang dihapus.
        """
        try:
            # 1. Resolve group_id dari sheet_name
            group_result = await self.db.execute(
                select(KPIGroupORM).where(
                    KPIGroupORM.sheet_name.ilike(f"%{source_sheet_name}%"),
                    KPIGroupORM.group_type == "master",
                )
            )
            groups = group_result.scalars().all()
            group_ids = [g.id for g in groups]

            if not group_ids:
                return 0

            # 2. Ambil dan hapus masters dalam grup-grup tersebut
            masters_result = await self.db.execute(
                select(KPIMasterORM).where(
                    KPIMasterORM.group_id.in_(group_ids)
                )
            )
            masters = masters_result.scalars().all()

            if not masters:
                return 0

            for master in masters:
                await self.db.delete(master)

            await self.db.commit()
            return len(masters)

        except Exception as e:
            await self.db.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"Gagal hapus KPI Masters: {str(e)}",
            )
