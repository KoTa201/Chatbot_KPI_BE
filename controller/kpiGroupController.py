"""
controller/kpiGroupController.py

Jembatan antara router (HTTP layer) dan service (business logic).

Tanggung jawab controller:
  - Meneruskan parameter dari router ke KPIGroupService.
  - Tidak mengandung logika bisnis — semua ada di service.
  - Memastikan setiap request mendapat instance service yang fresh
    dengan db session yang benar.

Pola ini konsisten dengan ChatbotController agar mudah di-maintain.
"""

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from schema.kpiGroupSchema import (
    KPIGroupCreate,
    KPIGroupUpdate,
    KPIGroupListResponse,
    KPIGroupResponse,
    MessageResponse,
    GroupTypeEnum
)
from service.kpiGroupService import KPIGroupService


class KPIGroupController:

    def __init__(self, db: AsyncSession):
        self.db: AsyncSession = db
        self.service: KPIGroupService = KPIGroupService(db)

    # ─── List ─────────────────────────────────────────────────────────────────

    async def list_groups(
        self,
        page:       int,
        limit:  int,
        tahun:      int | None,
        group_type: GroupTypeEnum | None,
        search:     str | None,
    ) -> KPIGroupListResponse:
        if limit < 1 or limit > 100:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="'limit' harus antara 1 dan 100.",
            )
        if page < 1:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="'page' tidak boleh negatif dan minimal 1.",
            )
        return await self.service.list_groups(
            page=page,
            limit=limit,
            tahun=tahun,
            group_type=group_type,
            search=search,
        )

    # ─── Get one ──────────────────────────────────────────────────────────────

    async def get_group(self, group_id: UUID) -> KPIGroupResponse:
        return await self.service.get_group(group_id=group_id)

    # ─── Create ───────────────────────────────────────────────────────────────

    async def create_group(self, payload: KPIGroupCreate) -> KPIGroupResponse:
        return await self.service.create_group(payload=payload)

    # ─── Update ───────────────────────────────────────────────────────────────

    async def update_group(
        self,
        group_id: UUID,
        payload:  KPIGroupUpdate,
    ) -> KPIGroupResponse:
        return await self.service.update_group(
            group_id=group_id,
            payload=payload,
        )

    # ─── Delete ───────────────────────────────────────────────────────────────

    async def delete_group(self, group_id: UUID) -> MessageResponse:
        result = await self.service.delete_group(group_id=group_id)
        return MessageResponse(message=result["message"])
