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
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from model.IngestionLog import IngestionLogORM
from model.KPIGroup import KPIGroup


class IngestionLogRepository:

    def __init__(self, db: AsyncSession):
        self.db: AsyncSession = db

    # ── CREATE ───────────────────────────────────────────────────────────────

    async def create(
        self,
        kpi_group_id: UUID,
        source_type: Optional[str] = None,
        group_name: Optional[str] = None,
    ) -> IngestionLogORM:
        """
        Buat IngestionLog baru dengan status awal 'failed'.

        kpi_group_id : grup (sheet) yang sedang diproses — wajib diisi.
        source_type  : 'master' atau 'tracker' — disimpan agar filter tetap
                       bekerja meski group dihapus di kemudian hari.
        """
        try:
            log = IngestionLogORM(
                kpi_group_id=kpi_group_id,
                source_type=source_type,
                group_name=group_name,
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

    async def list_with_group(
        self,
        offset: int,
        limit: int,
        source_type: str | None = None,
        status: str | None = None,
        start_datetime: datetime | None = None,
        end_datetime: datetime | None = None,
    ) -> tuple[list[tuple[IngestionLogORM, KPIGroup | None]], int]:
        filters = []
        if source_type is not None:
            filters.append(IngestionLogORM.source_type == source_type)
        if status is not None:
            filters.append(IngestionLogORM.status == status)
        if start_datetime is not None:
            filters.append(IngestionLogORM.created_at >= start_datetime)
        if end_datetime is not None:
            filters.append(IngestionLogORM.created_at <= end_datetime)

        count_query = select(func.count()).select_from(IngestionLogORM).outerjoin(
            KPIGroup, KPIGroup.id == IngestionLogORM.kpi_group_id,
        )
        for condition in filters:
            count_query = count_query.where(condition)

        total_result = await self.db.execute(count_query)
        total_count = total_result.scalar_one() or 0

        query = select(IngestionLogORM, KPIGroup).outerjoin(
            KPIGroup, KPIGroup.id == IngestionLogORM.kpi_group_id,
        )
        for condition in filters:
            query = query.where(condition)

        query = query.order_by(IngestionLogORM.created_at.desc()).offset(offset).limit(limit)
        result = await self.db.execute(query)
        return [(ingestion_log, kpi_group) for ingestion_log, kpi_group in result.all()], total_count

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
        return list(result.scalars().all())
