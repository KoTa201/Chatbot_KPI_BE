"""
router/kpiGroupRouter.py

Router untuk endpoints KPI Group management.
Style mengikuti ChatbotRouter — class-based, setup_routes() pattern.

Prefix yang direkomendasikan saat register di main.py:
  app.include_router(router, prefix="/kpi-groups", tags=["KPI Groups"])

Endpoints:
  GET    /kpi-groups/            → list semua grup (pagination + filter + search)
  GET    /kpi-groups/{id}        → detail satu grup
  POST   /kpi-groups/            → buat grup baru secara manual
  PATCH  /kpi-groups/{id}        → partial update (jika sheet_url berubah → re-ingest)
  DELETE /kpi-groups/{id}        → hard delete grup + cascade master/tracker
"""

from typing import Optional

from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from controller.kpiGroupController import KPIGroupController
from databaseConfig import get_db
from schema.kpiGroupSchema import (
    KPIGroupCreate,
    KPIGroupUpdate,
    KPIGroupListResponse,
    KPIGroupResponse,
    MessageResponse,
    VALID_GROUP_TYPES,
)


class KPIGroupRouter:
    """Router untuk endpoints KPI Group management."""

    def __init__(self):
        self.router: APIRouter = APIRouter()
        self.kpi_group_controller: KPIGroupController | None = None
        self.setup_routes()

    def setup_routes(self):
        """Register semua route KPI Group."""

        self.router.add_api_route(
            "/",
            self.list_groups,
            methods=["GET"],
            response_model=KPIGroupListResponse,
            summary="Daftar semua KPI Group",
            description=(
                "Ambil seluruh KPI Group dengan pagination, filter tipe grup "
                "('master' / 'tracker'), filter tahun, dan pencarian berdasarkan nama grup."
            ),
        )

        self.router.add_api_route(
            "/{group_id}",
            self.get_group,
            methods=["GET"],
            response_model=KPIGroupResponse,
            summary="Detail KPI Group",
            description="Ambil detail satu KPI Group berdasarkan UUID.",
        )

        self.router.add_api_route(
            "/",
            self.create_group,
            methods=["POST"],
            response_model=KPIGroupResponse,
            status_code=status.HTTP_201_CREATED,
            summary="Buat KPI Group baru",
            description=(
                "Tambah KPI Group baru secara manual. "
                "Dalam alur ingestion normal, grup dibuat otomatis. "
                "Endpoint ini berguna untuk pre-registrasi sheet sebelum data tersedia."
            ),
        )

        self.router.add_api_route(
            "/{group_id}",
            self.update_group,
            methods=["PATCH"],
            response_model=KPIGroupResponse,
            summary="Update KPI Group",
            description=(
                "Partial update KPI Group — kirim hanya field yang ingin diubah. "
                "**Perhatian:** Jika `sheet_url` diubah, sistem akan otomatis "
                "menjalankan ulang proses ingestion data dari sheet baru. "
                "Untuk grup bertipe `master`, field `tahun` wajib disertakan."
            ),
        )

        self.router.add_api_route(
            "/{group_id}",
            self.delete_group,
            methods=["DELETE"],
            response_model=MessageResponse,
            summary="Hapus KPI Group",
            description=(
                "Hard delete KPI Group beserta seluruh KPI Master dan Tracker "
                "yang berelasi (cascade). Operasi ini **tidak dapat dibatalkan**."
            ),
        )

    # ─── Handlers ─────────────────────────────────────────────────────────────

    async def list_groups(
        self,
        page:       int = Query(default=1, ge=1,
                                description="Nomor halaman"),
        limit:  int = Query(default=10, ge=1, le=100,
                            alias="page_size",
                            description="Jumlah item per halaman"),
        tahun: Optional[int] = Query(
            default=None,
            ge=2000,
            le=2100,
            description="Filter tahun KPI Group",
        ),
        group_type: Optional[str] = Query(
            default=None,
            description=f"Filter tipe grup: {sorted(VALID_GROUP_TYPES)}",
        ),
        search:     Optional[str] = Query(
            default=None,
            description="Cari berdasarkan nama grup",
        ),
        db: AsyncSession = Depends(get_db),
    ) -> KPIGroupListResponse:
        self.kpi_group_controller: KPIGroupController = KPIGroupController(db)
        return await self.kpi_group_controller.list_groups(
            page=page,
            limit=limit,
            tahun=tahun,
            group_type=group_type,
            search=search,
        )

    async def get_group(
        self,
        group_id: UUID = Path(..., description="UUID KPI Group"),
        db: AsyncSession = Depends(get_db),
    ) -> KPIGroupResponse:
        self.kpi_group_controller: KPIGroupController = KPIGroupController(db)
        return await self.kpi_group_controller.get_group(group_id=group_id)

    async def create_group(
        self,
        payload: KPIGroupCreate,
        db: AsyncSession = Depends(get_db),
    ) -> KPIGroupResponse:
        self.kpi_group_controller: KPIGroupController = KPIGroupController(db)
        return await self.kpi_group_controller.create_group(payload=payload)

    async def update_group(
        self,
        group_id: UUID = Path(..., description="UUID KPI Group"),
        payload:  KPIGroupUpdate = ...,
        db: AsyncSession = Depends(get_db),
    ) -> KPIGroupResponse:
        self.kpi_group_controller: KPIGroupController = KPIGroupController(db)
        return await self.kpi_group_controller.update_group(
            group_id=group_id,
            payload=payload,
        )

    async def delete_group(
        self,
        group_id: UUID = Path(..., description="UUID KPI Group"),
        db: AsyncSession = Depends(get_db),
    ) -> MessageResponse:
        self.kpi_group_controller: KPIGroupController = KPIGroupController(db)
        return await self.kpi_group_controller.delete_group(group_id=group_id)


# ─── Router instance ──────────────────────────────────────────────────────────
router = KPIGroupRouter().router
