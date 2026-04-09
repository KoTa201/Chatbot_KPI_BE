"""
router/recordRouter.py
Class-based router untuk KPI records endpoints.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from databaseConfig import get_db
from model.KPITracker import KPIRecordORM


class RecordRouter:
    """Router untuk endpoints KPI records query."""

    def __init__(self):
        self.router = APIRouter(prefix="/records", tags=["Records"])
        self.setup_routes()

    def setup_routes(self):
        """Register all record routes."""
        self.router.add_api_route(
            "/", self.get_records, methods=["GET"], summary="Ambil semua KPI records dengan filter")
        self.router.add_api_route(
            "/{record_id}", self.get_record, methods=["GET"], summary="Ambil satu KPI record by ID")
        self.router.add_api_route(
            "/", self.delete_all_records, methods=["DELETE"], summary="Hapus semua KPI records")

    async def get_records(
        self,
        nama_orang: Optional[str] = Query(
            default=None, description="Filter by nama orang"),
        tahun: Optional[int] = Query(
            default=None, description="Filter by tahun"),
        nama_kpi: Optional[str] = Query(
            default=None, description="Filter by nama KPI (partial match)"),
        limit: int = Query(default=50, le=500),
        offset: int = Query(default=0),
        db: AsyncSession = Depends(get_db),
    ):
        """Ambil KPI records dengan filter opsional."""
        query = select(KPIRecordORM)

        if nama_orang:
            query = query.where(
                KPIRecordORM.nama_orang.ilike(f"%{nama_orang}%"))
        if tahun:
            query = query.where(KPIRecordORM.tahun == tahun)
        if nama_kpi:
            query = query.where(KPIRecordORM.nama_kpi.ilike(f"%{nama_kpi}%"))

        query = query.order_by(KPIRecordORM.id.desc()
                               ).limit(limit).offset(offset)
        result = await db.execute(query)
        rows = result.scalars().all()

        return {
            "total": len(rows),
            "offset": offset,
            "limit": limit,
            "records": [
                {
                    "id": r.id,
                    "nama_kpi": r.nama_kpi,
                    "tahun": r.tahun,
                    "realisasi": r.realisasi,
                    "nama_orang": r.nama_orang,
                    "keterangan": r.keterangan,
                    "document_text": r.document_text,
                    "source_sheet": r.source_sheet_name,
                    "source_row": r.source_row,
                    "created_at": r.created_at,
                }
                for r in rows
            ],
        }

    async def get_record(self, record_id: int, db: AsyncSession = Depends(get_db)):
        """Ambil satu KPI record by ID."""
        result = await db.execute(
            select(KPIRecordORM).where(KPIRecordORM.id == record_id)
        )
        row = result.scalar_one_or_none()
        if not row:
            raise HTTPException(
                status_code=404, detail=f"Record ID {record_id} tidak ditemukan.")
        return row

    async def delete_all_records(self, db: AsyncSession = Depends(get_db)):
        """Hapus semua KPI records (reset)."""
        await db.execute(delete(KPIRecordORM))
        await db.commit()
        return {"message": "Semua KPI records berhasil dihapus."}


# ─── Router instance ─────────────────────────────────────────────────────
router = RecordRouter().router
