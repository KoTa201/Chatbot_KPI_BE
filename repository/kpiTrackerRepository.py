"""
repository/kpiTrackerRepository.py
Semua operasi CRUD ke database untuk KPI Tracker.

Perubahan dari versi sebelumnya:
  - bulk_insert: records kini harus berisi group_id + kpi_master_id,
    TIDAK lagi nama_kpi / tahun / source_sheet_name (dihapus dari model).
  - get_all_kpi_records: filter nama_kpi dan tahun kini via LEFT JOIN ke
    kpi_master_records. Filter nama_orang tetap langsung di tracker.
  - get_grouped_by_nama_kpi: GROUP BY kpi_master.kpi_name (bukan kolom lokal).
    sheet_names diambil dari kpi_groups via JOIN group_id.
  - get_grouped_by_nama_kpi_with_filters: sama, filter tahun ke kpi_master.tahun.
  - get_detail_records_by_nama_kpi: filter lewat JOIN ke kpi_master.kpi_name.
  - Hapus: self.ingestion_log (pindah ke IngestionLogRepository).
  - Hapus: create_ingestion_log (pindah ke IngestionLogRepository).

Interface publik (nama metode & parameter) TIDAK BERUBAH agar service tidak perlu
tahu detail JOIN internal — kecuali bulk_insert yang sekarang butuh group_id.
"""

from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from model.KPIGroup import KPIGroupORM
from model.KPIMaster import KPIMasterORM
from model.KPITracker import KPITrackerORM


class KPITrackerRepository:

    def __init__(self, db: AsyncSession):
        self.db = db

    # ================================================================ #
    #  CREATE                                                           #
    # ================================================================ #

    async def bulk_insert_kpi_records(self, records: list[dict]) -> int:
        """
        Bulk-insert KPI Tracker records.

        Records HARUS sudah berisi:
          - group_id      (UUID) — diisi ingestion service setelah KPIGroup dibuat
          - kpi_master_id (UUID | None) — diisi setelah master matching

        Kolom yang TIDAK LAGI ADA di records: nama_kpi, tahun, source_sheet_name.

        Returns:
            Jumlah baris yang berhasil disimpan.
        """
        if not records:
            return 0

        orm_records = [KPITrackerORM(**r) for r in records]
        self.db.add_all(orm_records)
        try:
            await self.db.commit()
            return len(orm_records)
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"Gagal simpan KPI Tracker records ke database: {str(e)}",
            )

    # ================================================================ #
    #  READ — single record                                            #
    # ================================================================ #

    async def get_kpi_record_by_id(self, record_id: UUID) -> Optional[KPITrackerORM]:
        try:
            result = await self.db.execute(
                select(KPITrackerORM).where(KPITrackerORM.id == record_id)
            )
            return result.scalar_one_or_none()
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Gagal ambil KPI record: {str(e)}",
            )

    # ================================================================ #
    #  READ — list dengan filter                                       #
    # ================================================================ #

    async def get_all_kpi_records(
        self,
        nama_kpi:   Optional[str] = None,
        tahun:      Optional[int] = None,
        nama_orang: Optional[str] = None,
        skip:       int = 0,
        limit:      int = 100,
    ) -> list[KPITrackerORM]:
        """
        Ambil KPI Tracker records dengan optional filters.

        nama_kpi dan tahun di-filter lewat LEFT JOIN ke kpi_master_records
        karena kolom tersebut sudah tidak ada di kpi_tracker_records.
        nama_orang masih langsung di tracker.
        """
        try:
            query = select(KPITrackerORM)

            # Jika filter yang butuh JOIN aktif, tambahkan LEFT JOIN
            if nama_kpi or tahun:
                query = query.outerjoin(
                    KPIMasterORM,
                    KPITrackerORM.kpi_master_id == KPIMasterORM.id,
                )
                if nama_kpi:
                    query = query.where(
                        KPIMasterORM.kpi_name.ilike(f"%{nama_kpi}%")
                    )
                if tahun:
                    query = query.where(KPIMasterORM.tahun == tahun)

            if nama_orang:
                query = query.where(
                    KPITrackerORM.nama_orang.ilike(f"%{nama_orang}%")
                )

            query = (
                query
                .order_by(desc(KPITrackerORM.created_at))
                .offset(skip)
                .limit(limit)
            )
            result = await self.db.execute(query)
            return result.scalars().all()

        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Gagal ambil KPI records: {str(e)}",
            )

    async def count_kpi_records(self) -> int:
        try:
            result = await self.db.execute(
                select(func.count(KPITrackerORM.id))
            )
            return result.scalar() or 0
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Gagal hitung KPI records: {str(e)}",
            )

    # ================================================================ #
    #  READ — grouped by KPI name (via JOIN kpi_master)                #
    # ================================================================ #

    async def get_grouped_by_nama_kpi(
        self, skip: int = 0, limit: int = 100
    ) -> list[dict]:
        """
        KPI Tracker dikelompokkan berdasarkan nama KPI dari kpi_master.

        Sebelumnya: GROUP BY kpi_tracker.nama_kpi (kolom lokal).
        Sekarang:   GROUP BY kpi_master.kpi_name via LEFT JOIN.

        Unmatched trackers (kpi_master_id IS NULL) dikelompokkan
        sebagai nama_kpi = 'UNMATCHED'.

        sheet_names sekarang dari kpi_groups.sheet_name via JOIN group_id.
        tahun_list dari kpi_master.tahun (satu nilai per master).
        """
        try:
            query = (
                select(
                    func.coalesce(
                        KPIMasterORM.kpi_name, "UNMATCHED"
                    ).label("nama_kpi"),
                    KPIMasterORM.id.label("kpi_master_id"),
                    func.count(KPITrackerORM.id).label("total_count"),
                    func.array_agg(
                        KPIMasterORM.tahun, distinct=True
                    ).label("tahun_list"),
                    func.array_agg(
                        KPIGroupORM.sheet_name, distinct=True
                    ).label("sheet_names"),
                    func.count(
                        KPITrackerORM.group_id, distinct=True
                    ).label("sheet_count"),
                    func.max(KPITrackerORM.updated_at).label("last_updated"),
                )
                .outerjoin(
                    KPIMasterORM,
                    KPITrackerORM.kpi_master_id == KPIMasterORM.id,
                )
                .join(
                    KPIGroupORM,
                    KPITrackerORM.group_id == KPIGroupORM.id,
                )
                .group_by(KPIMasterORM.id, KPIMasterORM.kpi_name)
                .order_by(desc(func.max(KPITrackerORM.updated_at)))
                .offset(skip)
                .limit(limit)
            )

            result = await self.db.execute(query)
            rows = result.fetchall()

            return [
                {
                    "nama_kpi":       row.nama_kpi,
                    "kpi_master_id":  str(row.kpi_master_id) if row.kpi_master_id else None,
                    "total_count":    row.total_count or 0,
                    "tahun_list":     sorted(
                        [t for t in (row.tahun_list or []) if t is not None]
                    ),
                    "sheet_names":    sorted(
                        [s for s in (row.sheet_names or []) if s is not None]
                    ),
                    "sheet_count":    row.sheet_count or 0,
                    "last_updated":   row.last_updated,
                }
                for row in rows
            ]

        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Gagal ambil grouped KPI records: {str(e)}",
            )

    async def get_grouped_by_nama_kpi_with_filters(
        self,
        tahun:      Optional[int] = None,
        nama_orang: Optional[str] = None,
        skip:       int = 0,
        limit:      int = 100,
    ) -> list[dict]:
        """
        Grouped by kpi_master.kpi_name dengan optional filters.

        tahun: filter ke kpi_master.tahun (bukan kolom lokal).
        nama_orang: filter langsung di tracker.

        Menggunakan SQL GROUP BY + WHERE (bukan Python grouping manual)
        agar efisien untuk data besar.
        """
        try:
            query = (
                select(
                    func.coalesce(
                        KPIMasterORM.kpi_name, "UNMATCHED"
                    ).label("nama_kpi"),
                    KPIMasterORM.id.label("kpi_master_id"),
                    func.count(KPITrackerORM.id).label("total_count"),
                    func.array_agg(
                        KPIMasterORM.tahun, distinct=True
                    ).label("tahun_list"),
                    func.array_agg(
                        KPIGroupORM.sheet_name, distinct=True
                    ).label("sheet_names"),
                    func.count(
                        KPITrackerORM.group_id, distinct=True
                    ).label("sheet_count"),
                    func.max(KPITrackerORM.updated_at).label("last_updated"),
                )
                .outerjoin(
                    KPIMasterORM,
                    KPITrackerORM.kpi_master_id == KPIMasterORM.id,
                )
                .join(
                    KPIGroupORM,
                    KPITrackerORM.group_id == KPIGroupORM.id,
                )
            )

            if tahun:
                query = query.where(KPIMasterORM.tahun == tahun)
            if nama_orang:
                query = query.where(
                    KPITrackerORM.nama_orang.ilike(f"%{nama_orang}%")
                )

            query = (
                query
                .group_by(KPIMasterORM.id, KPIMasterORM.kpi_name)
                .order_by(desc(func.max(KPITrackerORM.updated_at)))
                .offset(skip)
                .limit(limit)
            )

            result = await self.db.execute(query)
            rows = result.fetchall()

            return [
                {
                    "nama_kpi":      row.nama_kpi,
                    "kpi_master_id": str(row.kpi_master_id) if row.kpi_master_id else None,
                    "total_count":   row.total_count or 0,
                    "tahun_list":    sorted(
                        [t for t in (row.tahun_list or []) if t is not None]
                    ),
                    "sheet_names":   sorted(
                        [s for s in (row.sheet_names or []) if s is not None]
                    ),
                    "sheet_count":   row.sheet_count or 0,
                    "last_updated":  row.last_updated,
                }
                for row in rows
            ]

        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Gagal ambil grouped KPI records dengan filter: {str(e)}",
            )

    async def get_detail_records_by_nama_kpi(
        self,
        nama_kpi: str,
        skip:     int = 0,
        limit:    int = 100,
    ) -> list[KPITrackerORM]:
        """
        Detail records untuk satu KPI. Filter by kpi_master.kpi_name via JOIN.
        Sebelumnya: WHERE kpi_tracker.nama_kpi = nama_kpi (kolom lokal).
        Sekarang:   LEFT JOIN kpi_master WHERE kpi_master.kpi_name = nama_kpi.
        """
        try:
            query = (
                select(KPITrackerORM)
                .outerjoin(
                    KPIMasterORM,
                    KPITrackerORM.kpi_master_id == KPIMasterORM.id,
                )
                .where(KPIMasterORM.kpi_name == nama_kpi)
                .order_by(desc(KPITrackerORM.created_at))
                .offset(skip)
                .limit(limit)
            )
            result = await self.db.execute(query)
            return result.scalars().all()

        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Gagal ambil detail records by nama_kpi: {str(e)}",
            )

    # ================================================================ #
    #  UPDATE / DELETE                                                  #
    # ================================================================ #

    async def update_kpi_record(
        self, record_id: UUID, update_data: dict
    ) -> KPITrackerORM:
        try:
            record = await self.get_kpi_record_by_id(record_id)
            if not record:
                raise HTTPException(
                    status_code=404,
                    detail=f"KPI record dengan ID {record_id} tidak ditemukan",
                )
            for key, value in update_data.items():
                if hasattr(record, key):
                    setattr(record, key, value)
            await self.db.commit()
            await self.db.refresh(record)
            return record
        except HTTPException:
            raise
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"Gagal update KPI record: {str(e)}",
            )

    async def delete_kpi_record(self, record_id: UUID) -> bool:
        try:
            record = await self.get_kpi_record_by_id(record_id)
            if not record:
                raise HTTPException(
                    status_code=404,
                    detail=f"KPI record dengan ID {record_id} tidak ditemukan",
                )
            await self.db.delete(record)
            await self.db.commit()
            return True
        except HTTPException:
            raise
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"Gagal hapus KPI record: {str(e)}",
            )

    async def delete_kpi_records_by_ids(self, record_ids: list[UUID]) -> int:
        if not record_ids:
            return 0
        try:
            result = await self.db.execute(
                select(KPITrackerORM).where(KPITrackerORM.id.in_(record_ids))
            )
            records = result.scalars().all()
            for record in records:
                await self.db.delete(record)
            await self.db.commit()
            return len(records)
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"Gagal hapus multiple KPI records: {str(e)}",
            )

    async def delete_kpi_records_by_group(self, group_id: UUID) -> int:
        """
        Hapus semua tracker records dalam satu grup/sheet.
        Dipakai saat re-ingest sheet tracker yang sama.
        """
        try:
            result = await self.db.execute(
                select(KPITrackerORM).where(KPITrackerORM.group_id == group_id)
            )
            records = result.scalars().all()
            for record in records:
                await self.db.delete(record)
            await self.db.commit()
            return len(records)
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"Gagal hapus KPI records by group: {str(e)}",
            )
