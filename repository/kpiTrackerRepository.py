"""
repository/kpiTrackerRepository.py
Semua operasi CRUD ke database untuk proses ingestion KPI.
Tidak ada logika bisnis di sini — hanya interaksi langsung dengan ORM.
"""

import json
from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from model.IngestionLog import IngestionLogORM
from model.KPITracker import KPIRecordORM


class kpiTrackerRepository:

    def __init__(self, db: AsyncSession):
        self.db = db
        self.ingestion_log: IngestionLogORM = None

    # ------------------------------------------------------------------ #
    #  KPIRecord                                                           #
    # ------------------------------------------------------------------ #

    async def bulk_insert_kpi_records(self, records: list[dict]) -> int:
        """
        Bulk-insert list of KPI record dicts ke tabel KPIRecord.
        Kembalikan jumlah baris yang berhasil disimpan.
        Raise HTTP 500 jika commit gagal.
        """
        if not records:
            return 0

        orm_records = [KPIRecordORM(**r) for r in records]
        self.db.add_all(orm_records)
        try:
            await self.db.commit()
            return len(orm_records)
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"Gagal simpan KPI records ke database: {str(e)}",
            )

    async def get_kpi_record_by_id(self, record_id: UUID) -> Optional[KPIRecordORM]:
        """
        Ambil KPI record berdasarkan ID.
        Return: KPIRecordORM atau None jika tidak ditemukan.
        """
        try:
            query = select(KPIRecordORM).where(KPIRecordORM.id == record_id)
            result = await self.db.execute(query)
            return result.scalar_one_or_none()
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Gagal ambil KPI record: {str(e)}",
            )

    async def get_all_kpi_records(self,
                                  nama_kpi: Optional[str] = None,
                                  tahun: Optional[int] = None,
                                  nama_orang: Optional[str] = None,
                                  skip: int = 0,
                                  limit: int = 100) -> list[KPIRecordORM]:
        """
        Ambil semua KPI records dengan optional filters dan pagination.
        Params:
            nama_kpi: Filter by nama KPI (case-insensitive)
            tahun: Filter by tahun
            nama_orang: Filter by nama orang (case-insensitive)
            skip: Pagination offset
            limit: Pagination limit
        Return: List[KPIRecordORM]
        """
        try:
            query = select(KPIRecordORM)

            if nama_kpi:
                query = query.where(
                    KPIRecordORM.nama_kpi.ilike(f"%{nama_kpi}%"))
            if tahun:
                query = query.where(KPIRecordORM.tahun == tahun)
            if nama_orang:
                query = query.where(
                    KPIRecordORM.nama_orang.ilike(f"%{nama_orang}%"))

            query = query.offset(skip).limit(limit).order_by(
                desc(KPIRecordORM.created_at))
            result = await self.db.execute(query)
            return result.scalars().all()
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Gagal ambil KPI records: {str(e)}",
            )

    async def update_kpi_record(self, record_id: UUID, update_data: dict) -> KPIRecordORM:
        """
        Update KPI record berdasarkan ID.
        Return: KPIRecordORM yang sudah diupdate.
        Raise HTTPException 404 jika record tidak ditemukan.
        """
        try:
            # Cari record yang ada
            record = await self.get_kpi_record_by_id(record_id)
            if not record:
                raise HTTPException(
                    status_code=404,
                    detail=f"KPI record dengan ID {record_id} tidak ditemukan",
                )

            # Update fields yang diberikan
            for key, value in update_data.items():
                if hasattr(record, key):
                    setattr(record, key, value)

            await self.db.commit()
            await self.db.refresh(record)
            return record
        except HTTPException:
            raise
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"Gagal update KPI record: {str(e)}",
            )

    async def delete_kpi_record(self, record_id: UUID) -> bool:
        """
        Hapus KPI record berdasarkan ID.
        Return: True jika berhasil dihapus.
        Raise HTTPException 404 jika record tidak ditemukan.
        """
        try:
            # Cari record yang ada
            record = await self.get_kpi_record_by_id(record_id)
            if not record:
                raise HTTPException(
                    status_code=404,
                    detail=f"KPI record dengan ID {record_id} tidak ditemukan",
                )

            await self.db.delete(record)
            await self.db.commit()
            return True
        except HTTPException:
            raise
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"Gagal hapus KPI record: {str(e)}",
            )

    async def delete_kpi_records_by_ids(self, record_ids: list[UUID]) -> int:
        """
        Hapus multiple KPI records berdasarkan list IDs.
        Return: Jumlah records yang berhasil dihapus.
        """
        if not record_ids:
            return 0

        try:
            query = select(KPIRecordORM).where(KPIRecordORM.id.in_(record_ids))
            result = await self.db.execute(query)
            records = result.scalars().all()

            for record in records:
                await self.db.delete(record)

            await self.db.commit()
            return len(records)
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"Gagal hapus multiple KPI records: {str(e)}",
            )

    async def count_kpi_records(self) -> int:
        """
        Hitung total jumlah KPI records.
        Return: Total records.
        """
        try:
            from sqlalchemy import func
            query = select(func.count(KPIRecordORM.id))
            result = await self.db.execute(query)
            return result.scalar() or 0
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Gagal hitung KPI records: {str(e)}",
            )

    async def get_grouped_by_nama_kpi(self, skip: int = 0, limit: int = 100) -> list[dict]:
        """
        Ambil KPI records yang dikelompokkan berdasarkan nama_kpi.
        Return: List[Dict] dengan struktur group
        """
        try:
            from sqlalchemy import func
            
            # Query untuk aggregate data per nama_kpi
            query = select(
                KPIRecordORM.nama_kpi,
                func.count(KPIRecordORM.id).label('total_count'),
                func.array_agg(KPIRecordORM.tahun, distinct=True).label('tahun_list'),
                func.array_agg(KPIRecordORM.source_sheet_name, distinct=True).label('sheet_names'),
                func.count(distinct=KPIRecordORM.source_sheet_name).label('sheet_count'),
                func.max(KPIRecordORM.updated_at).label('last_updated'),
            ).group_by(KPIRecordORM.nama_kpi).order_by(desc(func.max(KPIRecordORM.updated_at)))
            
            # Apply pagination
            query = query.offset(skip).limit(limit)
            
            result = await self.db.execute(query)
            rows = result.all()
            
            # Convert ke list of dicts
            grouped_data = []
            for row in rows:
                grouped_data.append({
                    'nama_kpi': row[0],
                    'total_count': row[1] or 0,
                    'tahun_list': [t for t in (row[2] or []) if t is not None],
                    'sheet_names': [s for s in (row[3] or []) if s is not None],
                    'sheet_count': row[4] or 0,
                    'last_updated': row[5]
                })
            
            return grouped_data
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Gagal ambil grouped KPI records: {str(e)}",
            )

    async def get_grouped_by_nama_kpi_with_filters(self,
                                                    tahun: Optional[int] = None,
                                                    nama_orang: Optional[str] = None,
                                                    skip: int = 0,
                                                    limit: int = 100) -> list[dict]:
        """
        Ambil KPI records grouped by nama_kpi dengan optional filters.
        Return: List[Dict] dengan struktur group
        """
        try:
            from sqlalchemy import func
            
            # Base query
            query = select(KPIRecordORM)
            
            # Apply filters
            if tahun:
                query = query.where(KPIRecordORM.tahun == tahun)
            if nama_orang:
                query = query.where(KPIRecordORM.nama_orang.ilike(f"%{nama_orang}%"))
            
            # Get filtered records
            result = await self.db.execute(query)
            records = result.scalars().all()
            
            # Group manually
            groups = {}
            for record in records:
                kpi_name = record.nama_kpi
                if kpi_name not in groups:
                    groups[kpi_name] = {
                        'nama_kpi': kpi_name,
                        'total_count': 0,
                        'tahun_set': set(),
                        'sheet_set': set(),
                        'last_updated': None
                    }
                
                groups[kpi_name]['total_count'] += 1
                if record.tahun:
                    groups[kpi_name]['tahun_set'].add(record.tahun)
                if record.source_sheet_name:
                    groups[kpi_name]['sheet_set'].add(record.source_sheet_name)
                
                if record.updated_at:
                    current_updated = groups[kpi_name]['last_updated']
                    if current_updated is None or record.updated_at > current_updated:
                        groups[kpi_name]['last_updated'] = record.updated_at
            
            # Convert sets to lists dan sort
            grouped_data = []
            for group in groups.values():
                grouped_data.append({
                    'nama_kpi': group['nama_kpi'],
                    'total_count': group['total_count'],
                    'tahun_list': sorted(list(group['tahun_set'])),
                    'sheet_names': sorted(list(group['sheet_set'])),
                    'sheet_count': len(group['sheet_set']),
                    'last_updated': group['last_updated']
                })
            
            # Sort by last_updated descending
            grouped_data.sort(key=lambda x: x['last_updated'] or '', reverse=True)
            
            # Apply pagination
            total = len(grouped_data)
            grouped_data = grouped_data[skip:skip+limit]
            
            return grouped_data
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Gagal ambil grouped KPI records dengan filter: {str(e)}",
            )

    async def get_detail_records_by_nama_kpi(self, nama_kpi: str, 
                                             skip: int = 0, 
                                             limit: int = 100) -> list[KPIRecordORM]:
        """
        Ambil detail records untuk satu nama_kpi tertentu.
        Return: List[KPIRecordORM]
        """
        try:
            query = select(KPIRecordORM).where(
                KPIRecordORM.nama_kpi == nama_kpi
            ).offset(skip).limit(limit).order_by(desc(KPIRecordORM.created_at))
            
            result = await self.db.execute(query)
            return result.scalars().all()
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Gagal ambil detail records by nama_kpi: {str(e)}",
            )
