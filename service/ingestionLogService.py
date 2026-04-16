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
from uuid import UUID

from sqlalchemy import select
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
        group_type: Optional[str] = None,
    ) -> dict:
        """
        Fetch ingestion logs dengan optional filtering dan grouping.

        Args:
            limit: Jumlah maksimal logs yang dikembalikan
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
        # Normalize group_type untuk mapping ke source_type
        source_type_filter = self._normalize_group_type(group_type)

        # Special handling untuk tracker/master: ambil latest per source_id
        if source_type_filter in (None, ["kpi_tracker", "kpi_master"]):
            return await self._get_latest_logs_per_source(
                source_type_filter=source_type_filter,
                limit=limit,
            )

        # Fallback: ambil logs berdasarkan source_type tanpa grouping
        return await self._get_logs_by_source_type(
            source_type=source_type_filter,
            limit=limit,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # PRIVATE: Query builders
    # ─────────────────────────────────────────────────────────────────────────

    async def _get_latest_logs_per_source(
        self,
        source_type_filter: list[str] | None,
        limit: int,
    ) -> dict:
        """
        Fetch latest log per source_id (KPI Group).
        Ini memastikan hanya log terbaru per sheet yang ditampilkan.
        """
        # Build query
        latest_query = select(IngestionLogORM)

        if source_type_filter:
            latest_query = latest_query.where(
                IngestionLogORM.source_type.in_(source_type_filter)
            )
        else:
            latest_query = latest_query.where(
                IngestionLogORM.source_type.in_(["kpi_tracker", "kpi_master"])
            )

        # Order dan distinct untuk ambil latest per source_id
        latest_query = (
            latest_query.order_by(
                IngestionLogORM.source_type,
                IngestionLogORM.source_id,
                IngestionLogORM.created_at.desc(),
            )
            .distinct(IngestionLogORM.source_type, IngestionLogORM.source_id)
            .limit(limit)
        )

        latest_result = await self.db.execute(latest_query)
        latest_logs = latest_result.scalars().all()

        # Fetch KPI Groups untuk enrichment
        group_ids = [
            log.source_id for log in latest_logs if log.source_id
        ]
        groups_map = await self._fetch_groups_map(group_ids)

        # Transform dan return
        logs_payload = [
            self._format_log_response(log, groups_map.get(log.source_id))
            for log in latest_logs
        ]

        return {
            "total": len(logs_payload),
            "logs": logs_payload,
        }

    async def _get_logs_by_source_type(
        self,
        source_type: str,
        limit: int,
    ) -> dict:
        """Fetch logs berdasarkan source_type tanpa special grouping."""
        query = (
            select(IngestionLogORM)
            .where(IngestionLogORM.source_type == source_type)
            .order_by(IngestionLogORM.created_at.desc())
            .limit(limit)
        )

        result = await self.db.execute(query)
        logs = result.scalars().all()

        # Fetch KPI Groups untuk enrichment
        group_ids = [log.source_id for log in logs if log.source_id]
        groups_map = await self._fetch_groups_map(group_ids)

        # Transform dan return
        logs_payload = [
            self._format_log_response(log, groups_map.get(log.source_id))
            for log in logs
        ]

        return {
            "total": len(logs_payload),
            "logs": logs_payload,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # PRIVATE: Helpers
    # ─────────────────────────────────────────────────────────────────────────

    async def _fetch_groups_map(self, group_ids: list[UUID]) -> dict:
        """Fetch KPI Groups dan return sebagai mapping {id: group}."""
        if not group_ids:
            return {}

        group_result = await self.db.execute(
            select(KPIGroupORM).where(KPIGroupORM.id.in_(group_ids))
        )
        groups = group_result.scalars().all()
        return {g.id: g for g in groups}

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

        if group and log.source_type == "kpi_tracker":
            nama_orang = self._extract_nama_orang(group.nama_grup)

        return {
            "id": log.id,
            "sheet_name": sheet_name,
            "nama_orang": nama_orang,
            "total_rows": log.total_rows,
            "ingested": log.ingested_count,
            "failed": log.failed_count,
            "status": log.status,
            "source_type": log.source_type,
            "source_id": log.source_id,
            "created_at": log.created_at,
        }

    @staticmethod
    def _normalize_group_type(
        group_type: Optional[str],
    ) -> Optional[list[str]]:
        """
        Normalize group_type ke source_type list.

        Returns:
          - None → ambil semua (kpi_tracker + kpi_master)
          - "tracker" → ["kpi_tracker"]
          - "master" → ["kpi_master"]
        """
        if group_type is None:
            return None

        if group_type == "tracker":
            return ["kpi_tracker"]
        elif group_type == "master":
            return ["kpi_master"]

        # Fallback: treat as-is
        return [group_type]

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
