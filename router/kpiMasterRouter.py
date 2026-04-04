"""
router/kpiMasterRouter.py
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from controller.kpiMasterController import KPIMasterController
from databaseConfig import get_db
from schema.kpiMasterSchema import KPIMasterIngestionResponse

router = APIRouter()


@router.post(
    "",
    response_model=KPIMasterIngestionResponse,
    summary="Ingest KPI Master dari Google Sheets — upsert by tahun",
)
async def ingest_kpi_master(
    sheet_url: str = Query(..., description="URL Google Sheets KPI Master"),
    tahun: int = Query(..., description="Tahun KPI Master, contoh: 2024"),
    db: AsyncSession = Depends(get_db),
):
    controller = KPIMasterController(db)
    return await controller.ingest_kpi_master(sheet_url, tahun=tahun)


@router.get("/preview", summary="Preview KPI Master tanpa simpan")
async def preview_kpi_master(
    sheet_url: str = Query(...),
    tahun: int = Query(..., description="Tahun KPI Master, contoh: 2024"),
    db: AsyncSession = Depends(get_db),
):
    controller = KPIMasterController(db)
    return await controller.preview_kpi_master(sheet_url, tahun=tahun)
