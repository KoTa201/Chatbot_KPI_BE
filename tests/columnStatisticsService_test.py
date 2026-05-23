from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from databaseConfig import Base
from model.Base import GroupTypeEnum, RoleEnum
from model.KPIGroup import KPIGroup
from model.KPIMaster import KPIMaster
from model.KPITracker import KPITracker
from model.User import User
from service.columnStatisticsService import ColumnStatisticsService


async def _make_sqlite_session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(
        bind=engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, session_factory


@pytest.mark.asyncio
async def test_build_nl_to_sql_column_statistics_includes_numeric_and_unique_values():
    engine, session_factory = await _make_sqlite_session()
    try:
        async with session_factory() as db_session:
            user_id = uuid4()
            group_id = uuid4()
            master_id = uuid4()
            db_session.add_all(
                [
                    User(
                        id=user_id,
                        username="budi",
                        email="budi@example.com",
                        full_name="Budi Santoso",
                        hashed_password="hashed",
                        role=RoleEnum.karyawan,
                        is_active=True,
                    ),
                    KPIGroup(
                        id=group_id,
                        nama_grup="Tracker Sales",
                        group_type=GroupTypeEnum.TRACKER,
                        sheet_url="https://example.com/sheet",
                        sheet_id="sheet-1",
                        sheet_name="Maret",
                        tahun=2025,
                        is_active=True,
                    ),
                    KPIMaster(
                        id=master_id,
                        group_id=group_id,
                        category="KPI Sales",
                        kpi_name="Peningkatan Penjualan",
                        target="500",
                    ),
                    KPITracker(
                        group_id=group_id,
                        kpi_master_id=master_id,
                        user_id=user_id,
                        bulan_num=3,
                        realisasi="480",
                    ),
                    KPITracker(
                        group_id=group_id,
                        kpi_master_id=master_id,
                        user_id=user_id,
                        bulan_num=4,
                        realisasi="520",
                    ),
                ]
            )
            await db_session.commit()

            stats = await ColumnStatisticsService(db_session).build_nl_to_sql_statistics()

            assert "kpi_tracker_records.bulan_num" in stats
            assert "mean=3.5" in stats
            assert "min=3" in stats
            assert "max=4" in stats
            assert "non_null=2" in stats
            assert "non_zero=2" in stats
            assert "kpi_master_records.category" in stats
            assert "unique=['KPI Sales']" in stats
            assert "users.full_name" in stats
            assert "unique=['Budi Santoso']" in stats
    finally:
        await engine.dispose()
