"""
service/ingestionLogService.py
Service untuk menangani logika bisnis ingestion logs.
"""

import re
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from model.Base import GroupTypeEnum
from model.IngestionLog import IngestionLogORM
from model.KPIGroup import KPIGroupORM


class IngestionLogService:
    """Service untuk ingestion log operations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_ingestion_logs(
        self,
        limit: int,
        group_type: Optional[str] = None,
    ) -> dict:
        group_type_filter = self._normalize_group_type(group_type)
        return await self._get_latest_logs_per_group(
            group_type_filter=group_type_filter,
            limit=limit,
        )

    async def _get_latest_logs_per_group(
        self,
        group_type_filter: Optional[GroupTypeEnum],
        limit: int,
    ) -> dict:
        """Fetch latest log per kpi_group_id, optionally filtered by group_type."""
        query = select(IngestionLogORM).join(
            KPIGroupORM, IngestionLogORM.kpi_group_id == KPIGroupORM.id
        )

        if group_type_filter is not None:
            query = query.where(KPIGroupORM.group_type == group_type_filter)

        # DISTINCT ON (kpi_group_id) with ORDER BY kpi_group_id, created_at DESC
        # gives us the latest log per group
        query = (
            query.order_by(
                IngestionLogORM.kpi_group_id,
                IngestionLogORM.created_at.desc(),
            )
            .distinct(IngestionLogORM.kpi_group_id)
            .limit(limit)
        )

        result = await self.db.execute(query)
        logs = result.scalars().all()

        group_ids = [log.kpi_group_id for log in logs if log.kpi_group_id]
        groups_map = await self._fetch_groups_map(group_ids)

        logs_payload = [
            self._format_log_response(log, groups_map.get(log.kpi_group_id))
            for log in logs
        ]

        return {"total": len(logs_payload), "logs": logs_payload}

    async def _fetch_groups_map(self, group_ids: list[UUID]) -> dict:
        if not group_ids:
            return {}
        result = await self.db.execute(
            select(KPIGroupORM).where(KPIGroupORM.id.in_(group_ids))
        )
        groups = result.scalars().all()
        return {g.id: g for g in groups}

    def _format_log_response(
        self,
        log: IngestionLogORM,
        group: KPIGroupORM | None = None,
    ) -> dict:
        sheet_name = group.nama_grup if group else str(log.kpi_group_id)
        nama_orang = None

        if group and group.group_type == GroupTypeEnum.TRACKER:
            nama_orang = self._extract_nama_orang(group.nama_grup)

        source_type = None
        if group:
            if group.group_type == GroupTypeEnum.MASTER:
                source_type = "kpi_master"
            elif group.group_type == GroupTypeEnum.TRACKER:
                source_type = "kpi_tracker"

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
    def _normalize_group_type(group_type: Optional[str]) -> Optional[GroupTypeEnum]:
        if group_type is None:
            return None

        # Backward compatibility: frontend lama pakai source_type=kpi_tracker|kpi_master
        if group_type in {"tracker", "kpi_tracker"}:
            return GroupTypeEnum.TRACKER
        if group_type in {"master", "kpi_master"}:
            return GroupTypeEnum.MASTER
        return None

    @staticmethod
    def _extract_nama_orang(nama_grup: Optional[str]) -> Optional[str]:
        if not nama_grup:
            return None
        match = re.match(r"^KPI_Tracker_(.+?)_(20\d{2})$", nama_grup)
        if match:
            return match.group(1).replace("_", " ").strip()
        return None
