"""
routers/ingestion.py
Mendefinisikan route endpoint ingestion KPI.
Semua logika request/response/validation ada di controller.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from controller.ingestionController import IngestionController
from databaseConfig import get_db
from schema.ingestionSchema import BulkIngestionResponse, SheetIngestionResult

router = APIRouter()


@router.post(
    "/google-sheets",
    response_model=BulkIngestionResponse,
    summary="Ingest KPI dari Google Sheets — semua sheet otomatis",
)
async def ingest_from_google_sheets(
    sheet_url: str = Query(
        ...,
        description="URL Google Sheets yang sudah di-share ke email service account.",
    ),
    nama_orang_override: Optional[str] = Query(
        default=None,
        description=(
            "Opsional. Override nama orang untuk SEMUA sheet jika tidak bisa "
            "diekstrak dari judul. Jika diisi, nilai ini dipakai di semua sheet."
        ),
    ),
    skip_on_error: bool = Query(
        default=False,
        description=(
            "Jika True (default), sheet yang gagal di-parse dilewati dan dicatat "
            "sebagai warning. Jika False, satu sheet gagal akan membatalkan seluruh proses."
        ),
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Ingest data KPI dari **semua sheet/tab** dalam satu Google Spreadsheet ke PostgreSQL.

    **Nama orang dan periode (bulan/tahun) diekstrak otomatis** dari baris judul
    masing-masing sheet:

        KPI TRACKER – PIRMADI S  |  JANUARI 2025

    Parameter `nama_orang_override` hanya perlu diisi jika format judul berbeda
    dari template standar — nilai ini berlaku untuk semua sheet.

    **Prasyarat:**
    - Aktifkan Google Sheets API & Drive API di Google Cloud Console
    - Buat Service Account, download `credentials.json`, set path di `.env`
    - Share spreadsheet ke email service account sebagai **Viewer**
    """
    controller = IngestionController(db)
    return await controller.ingest_all_sheets_from_google_sheets(
        sheet_url=sheet_url,
        nama_orang_override=nama_orang_override,
        skip_on_error=skip_on_error,
    )


@router.get("/sheets/tabs", summary="List semua tab dalam spreadsheet")
async def list_sheet_tabs(
    sheet_url: str = Query(..., description="URL Google Sheets"),
):
    controller = IngestionController()
    return await controller.list_sheet_tabs(sheet_url=sheet_url)


@router.get("/sheets/preview", summary="Preview sheet + tampilkan metadata yang terekstrak")
async def preview_sheet(
    sheet_url: str = Query(...),
    sheet_name: Optional[str] = Query(default=None),
    sheet_index: int = Query(default=0),
):
    """
    Preview kolom, 5 baris pertama data, dan metadata yang berhasil diekstrak
    dari baris judul sheet — tanpa menyimpan apapun ke database.
    """
    controller = IngestionController()
    return await controller.preview_sheet(
        sheet_url=sheet_url,
        sheet_name=sheet_name,
        sheet_index=sheet_index,
    )


@router.get("/logs", summary="Riwayat ingestion")
async def get_ingestion_logs(
    limit: int = Query(default=20, le=100),
    db: AsyncSession = Depends(get_db),
):
    controller = IngestionController(db)
    return await controller.get_ingestion_logs(limit=limit)
