"""
service/kpiGroupService.py
"""

import math
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from model.KPIGroup import KPIGroupORM
from repository.kpiGroupRepository import KPIGroupRepository
from schema.kpiGroupSchema import (
    KPIGroupCreate,
    KPIGroupUpdate,
    KPIGroupListResponse,
    KPIGroupResponse,
    KPIGroupMasterRecord,   # nama baru — tidak bentrok dengan kpiMasterSchema
    KPIGroupTrackerRecord,  # nama baru — tidak bentrok dengan kpiTrackerSchema
)
from service.googleSheetService import GoogleSheetService
from service.kpiMasterIngestionService import KPIMasterIngestionService
from service.TrackeringestionService import TrackerIngestionService


class KPIGroupService:

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = KPIGroupRepository(db)

    # ─── Helper: ORM → KPIGroupResponse ──────────────────────────────────────

    def _build_response(
        self,
        group: KPIGroupORM,
        *,
        include_records: bool = False,
    ) -> KPIGroupResponse:
        """
        Konversi KPIGroupORM → KPIGroupResponse secara eksplisit.

        Tidak menggunakan model_validate(group) langsung karena Pydantic
        akan mengakses semua field termasuk relasi lazy yang belum di-load,
        yang memicu MissingGreenlet error di async SQLAlchemy.

        include_records=True  → konversi relasi yang sudah di-refresh oleh repo.
        include_records=False → list records kosong (untuk list & create/update response).
        """
        master_records:  list[KPIGroupMasterRecord] = []
        tracker_records: list[KPIGroupTrackerRecord] = []

        if include_records:
            if group.group_type == "master":
                # Hanya akses master_records — sudah di-refresh oleh repo.get_by_id()
                # tracker_records TIDAK diakses karena masih lazy
                master_records = [
                    KPIGroupMasterRecord.model_validate(r)
                    for r in group.master_records
                ]

            elif group.group_type == "tracker":
                # Hanya akses tracker_records — sudah di-refresh oleh repo.get_by_id()
                # master_records TIDAK diakses karena masih lazy
                tracker_records = [
                    KPIGroupTrackerRecord.model_validate(r)
                    for r in group.tracker_records
                ]

        return KPIGroupResponse(
            id=group.id,
            nama_grup=group.nama_grup,
            group_type=group.group_type,
            sheet_url=group.sheet_url,          # type: ignore[arg-type]
            sheet_id=group.sheet_id,
            sheet_name=group.sheet_name,
            tahun=group.tahun,
            is_scheduled=group.is_scheduled,
            is_active=group.is_active,
            created_at=group.created_at,
            updated_at=group.updated_at,
            master_records=master_records,
            tracker_records=tracker_records,
        )

    # ─── List ─────────────────────────────────────────────────────────────────

    async def list_groups(
        self,
        page:       int,
        page_size:  int,
        group_type: str | None = None,
        search:     str | None = None,
    ) -> KPIGroupListResponse:
        rows, total = await self.repo.list_groups(
            page=page,
            page_size=page_size,
            group_type=group_type,
            search=search,
        )
        return KPIGroupListResponse(
            total=total,
            page=page,
            page_size=page_size,
            total_pages=math.ceil(total / page_size) if total else 0,
            data=[self._build_response(r, include_records=False)
                  for r in rows],
        )

    # ─── Get one ──────────────────────────────────────────────────────────────

    async def get_group(self, group_id: UUID) -> KPIGroupResponse:
        """
        Fetch satu grup lengkap dengan records yang relevan.
        Repository sudah menangani conditional refresh berdasarkan group_type.
        """
        group = await self.repo.get_by_id(group_id)
        if not group:
            raise HTTPException(
                status_code=404,
                detail=f"KPI Group dengan id '{group_id}' tidak ditemukan.",
            )
        return self._build_response(group, include_records=True)

    # ─── Create ───────────────────────────────────────────────────────────────

    async def create_group(self, payload: KPIGroupCreate) -> KPIGroupResponse:
        sheet_url_str = str(payload.sheet_url)

        # Auto-fetch nama dan sheet_id dari Google Sheets jika tidak disertakan
        google_svc = GoogleSheetService()
        nama_grup = payload.nama_grup
        sheet_id = payload.sheet_id

        if not nama_grup or not sheet_id:
            try:
                if not nama_grup:
                    nama_grup = google_svc.get_spreadsheet_title(sheet_url_str)
                if not sheet_id:
                    # Ekstrak sheet_id dari URL
                    import re
                    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", sheet_url_str)
                    sheet_id = match.group(1) if match else ""
            except Exception:
                nama_grup = nama_grup or sheet_url_str
                sheet_id = sheet_id or ""

        group = await self.repo.get_or_create(
            sheet_id=sheet_id,
            group_type=payload.group_type,
            sheet_url=sheet_url_str,
            sheet_name=payload.sheet_name,
            nama_grup=nama_grup,
            tahun=payload.tahun,
            is_scheduled=payload.is_scheduled,
            is_active=payload.is_active,
        )
        await self.db.commit()
        await self.db.refresh(group)
        return self._build_response(group, include_records=False)

    # ─── Update ───────────────────────────────────────────────────────────────

    async def update_group(
        self,
        group_id: UUID,
        payload:  KPIGroupUpdate,
    ) -> KPIGroupResponse:
        """
        Partial update. Jika sheet_url berubah → jalankan ulang ingestion
        sesuai group_type setelah perubahan URL tersimpan ke DB.
        Response tidak menyertakan records — GET /{id} untuk data terbaru.
        """
        existing = await self.repo.get_by_id(group_id)
        if not existing:
            raise HTTPException(
                status_code=404,
                detail=f"KPI Group dengan id '{group_id}' tidak ditemukan.",
            )

        update_fields = payload.model_dump(exclude_none=True)

        if "sheet_url" in update_fields:
            update_fields["sheet_url"] = str(update_fields["sheet_url"])

        sheet_url_changed = (
            "sheet_url" in update_fields
            and update_fields["sheet_url"] != existing.sheet_url
        )

        if sheet_url_changed and existing.group_type == "master" and not payload.tahun:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Field `tahun` wajib disertakan saat mengubah sheet_url "
                    "pada KPI Group bertipe 'master'."
                ),
            )

        group = await self.repo.update(group_id=group_id, fields=update_fields)
        await self.db.commit()
        await self.db.refresh(group)

        if sheet_url_changed:
            new_url = update_fields["sheet_url"]
            if existing.group_type == "master":
                svc = KPIMasterIngestionService(self.db)
                await svc.ingest_kpi_master(sheet_url=new_url, tahun=payload.tahun)
            elif existing.group_type == "tracker":
                svc = TrackerIngestionService(self.db)
                await svc.ingest_all_sheets(
                    sheet_url=new_url,
                    tahun=payload.tahun or 2026,
                    skip_on_error=True,
                )

        return self._build_response(group, include_records=False)

    # ─── Delete ───────────────────────────────────────────────────────────────

    async def delete_group(self, group_id: UUID) -> dict:
        await self.repo.delete(group_id)
        await self.db.commit()
        return {"message": f"KPI Group '{group_id}' berhasil dihapus."}
