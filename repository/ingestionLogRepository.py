"""
repository/ingestionLogRepository.py
Operasi DB untuk IngestionLog — append-only, tidak ada update kecuali
status akhir (running → success / partial / failed).

Pola dua langkah:
  1. create()        → buat log dengan status='running' sebelum proses mulai
  2. update_status() → update setelah proses selesai (berhasil atau gagal)

Ini memastikan setiap ingestion tercatat bahkan jika prosesnya crash di tengah.
"""

from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from model.IngestionLog import IngestionLogORM
from model.Base import IngestionSourceType


class IngestionLogRepository:

    def __init__(self, db: AsyncSession):
        self.db = db

    # ── CREATE ───────────────────────────────────────────────────────────────

    async def create(
        self,
        source_type: str,           # 'scheduler' | 'kpi_master' | 'kpi_tracker'
        source_id: UUID,            # group_id atau scheduler_id
        sheet_url: str,
        sheet_id: Optional[str] = None,
        sheet_name: Optional[str] = None,
        scheduler_id: Optional[UUID] = None,
    ) -> IngestionLogORM:
        """
        Buat IngestionLog baru dengan status awal 'running'.

        source_id diisi dengan:
          - group_id   jika source_type = 'kpi_master' atau 'kpi_tracker'
          - scheduler_id jika source_type = 'scheduler'
        """
        try:
            log = IngestionLogORM(
                source_type=source_type,
                source_id=source_id,
                scheduler_id=scheduler_id,
                sheet_url=sheet_url,
                sheet_id=sheet_id,
                sheet_name=sheet_name,
                status="running",
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
        status: str,                        # 'success' | 'partial' | 'failed'
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

    async def get_by_source(
        self,
        source_type: str,
        source_id: UUID,
        limit: int = 10,
    ) -> list[IngestionLogORM]:
        """Audit: ambil semua log ingestion untuk satu entitas."""
        result = await self.db.execute(
            select(IngestionLogORM)
            .where(
                IngestionLogORM.source_type == source_type,
                IngestionLogORM.source_id == source_id,
            )
            .order_by(IngestionLogORM.created_at.desc())
            .limit(limit)
        )
        return result.scalars().all()
