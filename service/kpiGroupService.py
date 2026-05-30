"""
service/kpiGroupService.py
"""

import math
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from model.KPIGroup import KPIGroup
from repository.ingestionLogRepository import IngestionLogRepository
from repository.kpiGroupRepository import KPIGroupRepository
from repository.kpiMasterRepository import KPIMasterRepository
from schema.kpiGroupSchema import (
    KPIGroupCreate,
    KPIGroupUpdate,
)
from service.googleSheetService import GoogleSheetService
from service.kpiMasterIngestionService import KPIMasterIngestionService
from service.kpiMasterService import KPIMasterService
from service.TrackeringestionService import TrackerIngestionService
from repository.kpiTrackerRepository import KPITrackerRepository


class KPIGroupService:

    def __init__(self, db: AsyncSession):
        self.db: AsyncSession = db
        self.repo: KPIGroupRepository = KPIGroupRepository(db)

    # ─── List ─────────────────────────────────────────────────────────────────

    async def list_groups(
        self,
        page:       int,
        limit:      int,
        tahun:      int | None = None,
        group_type: str | None = None,
        search:     str | None = None,
    ) -> tuple[list[KPIGroup], int]:
        """Kembalikan (rows, total) — formatting ada di controller."""
        rows, total = await self.repo.list_groups(
            page=page,
            limit=limit,
            tahun=tahun,
            group_type=group_type,
            search=search,
        )
        return rows, total

    # ─── Get one ──────────────────────────────────────────────────────────────

    async def get_group(self, group_id: UUID) -> KPIGroup:
        """
        Fetch satu grup lengkap dengan records yang relevan.
        Repository sudah menangani conditional refresh berdasarkan group_type.
        """
        return await self._get_or_404(group_id)

    # ─── Create ───────────────────────────────────────────────────────────────

    async def create_group(self, payload: KPIGroupCreate) -> KPIGroup:
        sheet_url_str = str(payload.sheet_url)

        google_svc = GoogleSheetService()
        nama_grup = payload.nama_grup
        sheet_id = payload.sheet_id

        if not nama_grup or not sheet_id:
            try:
                if not nama_grup:
                    nama_grup = google_svc.get_spreadsheet_title(sheet_url_str)
                if not sheet_id:
                    import re
                    match = re.search(
                        r"/spreadsheets/d/([a-zA-Z0-9_-]+)", sheet_url_str)
                    sheet_id = match.group(1) if match else ""
            except Exception:
                nama_grup = nama_grup or sheet_url_str
                sheet_id = sheet_id or ""

        return await self.repo.get_or_create_committed(
            sheet_id=sheet_id,
            group_type=payload.group_type,
            sheet_url=sheet_url_str,
            sheet_name=payload.sheet_name,
            nama_grup=nama_grup,
            tahun=payload.tahun,
            is_active=payload.is_active,
        )

    # ─── Update ───────────────────────────────────────────────────────────────

    async def update_group(
        self,
        group_id: UUID,
        payload:  KPIGroupUpdate,
    ) -> KPIGroup:
        existing = await self._get_or_404(group_id)

        update_fields = payload.model_dump(exclude_none=True)

        if "sheet_url" in update_fields:
            update_fields["sheet_url"] = str(update_fields["sheet_url"])

        sheet_url_changed = (
            "sheet_url" in update_fields
            and update_fields["sheet_url"] != existing.sheet_url
        )
        tahun_changed = (
            "tahun" in update_fields
            and update_fields["tahun"] != existing.tahun
        )

        if sheet_url_changed or (existing.group_type == "master" and tahun_changed):
            if existing.group_type == "master":
                kpi_repo = KPIMasterRepository(self.db)
                kpi_service = KPIMasterService(repository=kpi_repo)
                log_repo = IngestionLogRepository(self.db)
                svc = KPIMasterIngestionService(
                    db=self.db,
                    kpi_repo=kpi_repo,
                    kpi_service=kpi_service,
                    log_repo=log_repo,
                    group_repo=self.repo,
                )
                await svc.update_and_reingest(
                    group_id=group_id,
                    sheet_url=update_fields["sheet_url"] if sheet_url_changed else None,
                    tahun=payload.tahun,
                )
            elif existing.group_type == "tracker":
                kpi_repo = KPITrackerRepository(self.db)
                log_repo = IngestionLogRepository(self.db)
                svc = TrackerIngestionService(
                    self.db, group_repo=self.repo, log_repo=log_repo, tracker_repo=kpi_repo)
                await svc.ingest_all_sheets(
                    sheet_url=update_fields["sheet_url"] if sheet_url_changed else str(existing.sheet_url),
                    tahun=payload.tahun if payload.tahun is not None else existing.tahun,
                    skip_on_error=True,
                    existing_group_id=existing.id,
                )
        elif update_fields:
            await self.repo.update_committed(group_id=group_id, fields=update_fields)

        group = await self._get_or_404(group_id)

        return group 

    # ─── Delete ───────────────────────────────────────────────────────────────

    async def delete_group(self, group_id: UUID) -> dict:
        await self._get_or_404(group_id)
        await self.repo.delete_committed(group_id)

        return {"message": f"KPI Group '{group_id}' berhasil dihapus."}

    async def _get_or_404(self, group_id: UUID) -> KPIGroup:
        group = await self.repo.get_by_id(group_id)
        if not group:
            raise HTTPException(
                status_code=404,
                detail=f"KPI Group dengan id '{group_id}' tidak ditemukan.",
            )
        return group
