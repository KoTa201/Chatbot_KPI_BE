"""
repository/ingestionLogRepository.py
Operasi DB untuk IngestionLog — append-only, tidak ada update kecuali
status akhir (failed -> success jika proses berhasil).

Pola dua langkah:
    1. create()        → buat log dengan status='failed' (default aman)
    2. update_status() → update setelah proses selesai (success/failed)

Ini memastikan setiap ingestion tercatat bahkan jika prosesnya crash di tengah.
"""

from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from model.IngestionLog import IngestionLogORM


class IngestionLogRepository:

    def __init__(self, db: AsyncSession):
        self.db = db

    # ── CREATE ───────────────────────────────────────────────────────────────

    async def create(
        self,
        kpi_group_id: UUID,
        scheduler_id: Optional[UUID] = None,
    ) -> IngestionLogORM:
        """
        Buat IngestionLog baru dengan status awal 'failed'.

        kpi_group_id : grup (sheet) yang sedang diproses — wajib diisi.
        scheduler_id : diisi hanya jika ingestion dipicu oleh scheduler.
        """
        try:
            log = IngestionLogORM(
                kpi_group_id=kpi_group_id,
                scheduler_id=scheduler_id,
                status="failed",
            )
            self.db.add(log)
            await self.db.flush()   # Dapat ID tanpa commit — masih satu transaksi
            return log

        except Exception as e:
            await self.db.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"Gagal buat IngestionLog: {str(e)}",
            )

    # ── UPDATE STATUS ────────────────────────────────────────────────────────

    async def update_status(
        self,
        log_id: UUID,
        status: str,                        # 'success' | 'failed'
        total_rows: int = 0,
        ingested_count: int = 0,
        failed_count: int = 0,
        errors: Optional[str] = None,
    ) -> IngestionLogORM:
        """
        Update status akhir IngestionLog setelah proses selesai.
        Dipanggil sekali — log tidak pernah diubah lagi setelah ini.
        """
        try:
            log = await self.db.get(IngestionLogORM, log_id)
            if not log:
                raise HTTPException(
                    status_code=404,
                    detail=f"IngestionLog {log_id} tidak ditemukan",
                )

            log.status = status
            log.total_rows = total_rows
            log.ingested_count = ingested_count
            log.failed_count = failed_count
            log.errors = errors

            await self.db.commit()
            await self.db.refresh(log)
            return log

        except HTTPException:
            raise
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"Gagal update status IngestionLog: {str(e)}",
            )

    # ── READ ─────────────────────────────────────────────────────────────────

    async def get_by_group(
        self,
        kpi_group_id: UUID,
        limit: int = 10,
    ) -> list[IngestionLogORM]:
        """Audit: ambil semua log ingestion untuk satu KPIGroup."""
        result = await self.db.execute(
            select(IngestionLogORM)
            .where(IngestionLogORM.kpi_group_id == kpi_group_id)
            .order_by(IngestionLogORM.created_at.desc())
            .limit(limit)
        )
        return result.scalars().all()
