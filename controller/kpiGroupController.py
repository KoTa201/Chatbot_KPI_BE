"""
controller/kpiGroupController.py
"""

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from model.KPIGroup import KPIGroup
from schema.kpiGroupSchema import (
    KPIGroupCreate,
    KPIGroupUpdate,
    KPIGroupListResponse,
    KPIGroupResponse,
    KPIGroupMasterRecord,
    KPIGroupTrackerRecord,
    MessageResponse,
    GroupTypeEnum,
)
from exceptions import translate_app_errors
from service.kpiGroupService import KPIGroupService
from utils.pagination import calculate_total_pages, validate_limit, validate_page


class KPIGroupController:

    def __init__(self, db: AsyncSession):
        self.db: AsyncSession = db
        self.service: KPIGroupService = KPIGroupService(db)

    # ─── List ─────────────────────────────────────────────────────────────────

    async def list_groups(
        self,
        page:       int = 1,
        limit:      int = 10,
        tahun:      int | None = None,
        group_type: GroupTypeEnum | None = None,
        search:     str | None = None,
    ) -> KPIGroupListResponse:
        try:
            page = validate_page(page)
            limit = validate_limit(limit)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(e),
            )

        rows, total = await self.service.list_groups(
            page=page,
            limit=limit,
            tahun=tahun,
            group_type=group_type,
            search=search,
        )
        return KPIGroupListResponse(
            total=total,
            page=page,
            limit=limit,
            total_pages=calculate_total_pages(total, limit),
            data=[self._build_response(r, include_records=False)
                  for r in rows],
        )

    # ─── Get one ──────────────────────────────────────────────────────────────

    @translate_app_errors
    async def get_group(self, group_id: UUID) -> KPIGroupResponse:
        group = await self.service.get_group(group_id=group_id)
        return self._build_response(group, include_records=True)

    # ─── Create ───────────────────────────────────────────────────────────────

    @translate_app_errors
    async def create_group(self, payload: KPIGroupCreate) -> KPIGroupResponse:
        group = await self.service.create_group(payload=payload)
        return self._build_response(group, include_records=False)

    # ─── Update ───────────────────────────────────────────────────────────────

    @translate_app_errors
    async def update_group(
        self,
        group_id: UUID,
        payload:  KPIGroupUpdate,
    ) -> KPIGroupResponse:
        group = await self.service.update_group(group_id=group_id, payload=payload)
        return self._build_response(group, include_records=False)

    # ─── Delete ───────────────────────────────────────────────────────────────

    @translate_app_errors
    async def delete_group(self, group_id: UUID) -> MessageResponse:
        response = await self.service.delete_group(group_id=group_id)
        return MessageResponse(message=response["message"])

    # ─── Helper: ORM → KPIGroupResponse ──────────────────────────────────────

    @staticmethod
    def _build_response(
        group: KPIGroup,
        *,
        include_records: bool = False,
    ) -> KPIGroupResponse:
        """
        Konversi KPIGroup → KPIGroupResponse secara eksplisit.

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
                master_records = [
                    KPIGroupMasterRecord.model_validate({
                        "id": r.id,
                        "group_id": r.group_id,
                        "tahun": group.tahun,
                        "category": r.category,
                        "kpi_name": r.kpi_name,
                        "definisi_operasional": r.definisi_operasional,
                        "target": r.target,
                        "achieve": r.achieve,
                        "partial": r.partial,
                        "fail": r.fail,
                        "pic_users": r.pic_users,
                        "created_at": r.created_at,
                    })
                    for r in group.master_records
                ]
            elif group.group_type == "tracker":
                tracker_records = [
                    KPIGroupTrackerRecord.model_validate({
                        "id": r.id,
                        "group_id": r.group_id,
                        "kpi_master_id": r.kpi_master_id,
                        "tahun": group.tahun,
                        "bulan_num": r.bulan_num,
                        "realisasi": r.realisasi,
                        "keterangan": r.keterangan,
                        "user": r.user,
                        "created_at": r.created_at,
                        "updated_at": r.updated_at,
                    })
                    for r in group.tracker_records
                ]

        return KPIGroupResponse(
            id=group.id,
            nama_grup=group.nama_grup,
            group_type=group.group_type,
            sheet_url=group.sheet_url,
            sheet_id=group.sheet_id,
            sheet_name=group.sheet_name,
            tahun=group.tahun,
            is_active=group.is_active,
            created_at=group.created_at,
            updated_at=group.updated_at,
            master_records=master_records,
            tracker_records=tracker_records,
        )
