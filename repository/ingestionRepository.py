"""
repository/ingestionRepository.py
Semua operasi CRUD ke database untuk proses ingestion KPI.
Tidak ada logika bisnis di sini — hanya interaksi langsung dengan ORM.
"""

import json
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from model.IngestionLog import IngestionLogORM
from model.KPITracker import KPIRecordORM


class IngestionRepository:

    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------ #
    #  KPIRecord                                                           #
    # ------------------------------------------------------------------ #

    async def bulk_insert_kpi_records(self, records: list[dict]) -> int:
        """
        Bulk-insert list of KPI record dicts ke tabel KPIRecord.
        Kembalikan jumlah baris yang berhasil disimpan.
        Raise HTTP 500 jika commit gagal.
        """
        if not records:
            return 0

        orm_records = [KPIRecordORM(**r) for r in records]
        self.db.add_all(orm_records)
        try:
            await self.db.commit()
            return len(orm_records)
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"Gagal simpan KPI records ke database: {str(e)}",
            )

    # ------------------------------------------------------------------ #
    #  IngestionLog                                                        #
    # ------------------------------------------------------------------ #

    async def create_ingestion_log(
        self,
        sheet_url: str,
        spreadsheet_id: str,
        sheet_name: str,
        nama_orang: Optional[str],
        total_rows: int,
        ingested_count: int,
        errors: list[str],
        status: str,
        source_type: str = "kpi_tracker",
    ) -> IngestionLogORM:
        """
        Insert satu baris log ingestion ke tabel IngestionLog.
        Kembalikan instance ORM yang sudah ter-refresh (id terisi).
        """
        log = IngestionLogORM(
            sheet_url=sheet_url,
            sheet_id=spreadsheet_id,
            sheet_name=sheet_name,
            nama_orang=nama_orang,
            total_rows=total_rows,
            ingested_count=ingested_count,
            failed_count=len(errors),
            errors=json.dumps(errors, ensure_ascii=False) if errors else None,
            status=status,
            source_type=source_type,
        )
        self.db.add(log)
        await self.db.commit()
        await self.db.refresh(log)
        return log

    async def get_ingestion_logs(
        self,
        limit: int,
        source_type: Optional[str] = None,
    ) -> list[IngestionLogORM]:
        """
        Ambil riwayat ingestion log, diurutkan dari terbaru.
        Kembalikan list ORM instance.
        """
        query = select(IngestionLogORM).order_by(IngestionLogORM.created_at.desc())
        if source_type:
            query = query.where(IngestionLogORM.source_type == source_type)
        result = await self.db.execute(query.limit(limit))
        return result.scalars().all()
