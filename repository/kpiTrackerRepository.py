"""Repository operasi database untuk ingestion KPI Tracker."""

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
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
