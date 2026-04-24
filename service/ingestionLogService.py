"""
service/ingestionLogService.py
Service untuk menangani logika bisnis ingestion logs.

Responsibilities:
  - Fetch dan transform ingestion logs dari database
  - Resolve group metadata (nama_grup, nama_orang dari KPIGroup)
  - Format response sesuai dengan output schema
  - Handle berbagai filter dan sorting strategies
"""

import re
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from model.IngestionLog import IngestionLogORM
from model.KPIGroup import KPIGroupORM


class IngestionLogService:
    """Service untuk ingestion log operations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ─────────────────────────────────────────────────────────────────────────
    # PUBLIC: Get logs
    # ─────────────────────────────────────────────────────────────────────────

    async def get_ingestion_logs(
        self,
        limit: int,
        offset: int = 0,
        group_type: Optional[str] = None,
    ) -> dict:
        """
        Fetch ingestion logs dengan optional filtering dan grouping.

        Args:
            limit: Jumlah maksimal logs yang dikembalikan
            offset: Posisi awal data untuk pagination
            group_type: Filter berdasarkan group_type ('tracker', 'master', atau None untuk semua)

        Returns:
            {
                "total": int,
                "logs": [
                    {
                        "id": UUID,
                        "sheet_name": str,
                        "nama_orang": str | None,
                        "total_rows": int,
                        "ingested": int,
                        "failed": int,
                        "status": str,
                        "source_type": str,
                        "source_id": UUID,
                        "created_at": datetime,
                    }
                ]
            }
        """
        count_query = select(func.count()).select_from(IngestionLogORM).join(
            KPIGroupORM,
            KPIGroupORM.id == IngestionLogORM.kpi_group_id,
        )

        if group_type is not None:
            count_query = count_query.where(KPIGroupORM.group_type == group_type)

        total_result = await self.db.execute(count_query)
        total_count = int(total_result.scalar_one() or 0)

        query = select(IngestionLogORM, KPIGroupORM).join(
            KPIGroupORM,
            KPIGroupORM.id == IngestionLogORM.kpi_group_id,
        )

        if group_type is not None:
            query = query.where(KPIGroupORM.group_type == group_type)

        query = query.order_by(IngestionLogORM.created_at.desc()).offset(offset).limit(limit)

        result = await self.db.execute(query)
        rows = result.all()

        logs_payload = [
            self._format_log_response(log, group)
            for log, group in rows
        ]

        return {
            "total": total_count,
            "logs": logs_payload,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # PRIVATE: Query builders
    # ─────────────────────────────────────────────────────────────────────────

    # (Legacy helper methods removed: source_type/source_id no longer exist
    # on IngestionLogORM after KPIGroup migration.)

    # ─────────────────────────────────────────────────────────────────────────
    # PRIVATE: Helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _format_log_response(
        self,
        log: IngestionLogORM,
        group: KPIGroupORM | None = None,
    ) -> dict:
        """
        Transform IngestionLogORM ke response dict.

        Jika group tersedia, gunakan nama_grup sebagai sheet_name dan
        extract nama_orang dari nama_grup (untuk tracker).
        """
        sheet_name = group.nama_grup if group else log.sheet_name
        nama_orang = None

        source_type = self._map_source_type(group.group_type) if group else "kpi_tracker"

        if group and source_type == "kpi_tracker":
            nama_orang = self._extract_nama_orang(group.nama_grup)

        return {
            "id": log.id,
            "sheet_name": sheet_name,
            "nama_orang": nama_orang,
            "total_rows": log.total_rows,
            "ingested": log.ingested_count,
            "failed": log.failed_count,
            "status": log.status,
            "source_type": source_type,
            "source_id": log.kpi_group_id,
            "created_at": log.created_at,
        }

    @staticmethod
    def _map_source_type(group_type: str) -> str:
        if group_type == "master":
            return "kpi_master"
        return "kpi_tracker"

    @staticmethod
    def _extract_nama_orang(nama_grup: Optional[str]) -> Optional[str]:
        """
        Extract nama orang dari nama_grup.

        Pattern: KPI_Tracker_<Nama Orang>_<Tahun>
        Example: KPI_Tracker_Budi_Santoso_2025 → "Budi Santoso"
        """
        if not nama_grup:
            return None

        match = re.match(r"^KPI_Tracker_(.+?)_(20\d{2})$", nama_grup)
        if match:
            return match.group(1).replace("_", " ").strip()

        return None
