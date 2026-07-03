import json
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from databaseConfig import Base
from model.Base import GroupTypeEnum, RoleEnum
from model.KPIGroup import KPIGroup
from model.KPIMaster import KPIMaster
from model.KPITracker import KPITracker
from model.NlSqlStatsCache import NlSqlStatsCache
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


async def _seed(db_session: AsyncSession) -> None:
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


@pytest.mark.asyncio
async def test_get_statistics_text_includes_numeric_and_unique_values():
    engine, session_factory = await _make_sqlite_session()
    try:
        async with session_factory() as db_session:
            await _seed(db_session)

            stats = await ColumnStatisticsService(db_session).get_statistics_text()

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


@pytest.mark.asyncio
async def test_refresh_statistics_persists_valid_json_single_row():
    engine, session_factory = await _make_sqlite_session()
    try:
        async with session_factory() as db_session:
            await _seed(db_session)
            service = ColumnStatisticsService(db_session)

            stats = await service.refresh_statistics()

            # Return value is a serializable dict.
            assert isinstance(stats, dict)
            assert stats["kpi_master_records.category"]["type"] == "text"

            # Exactly one row, id=1, holding valid JSON.
            rows = (await db_session.execute(select(NlSqlStatsCache))).scalars().all()
            assert len(rows) == 1
            assert rows[0].id == 1
            parsed = json.loads(rows[0].stats_json)
            assert parsed == json.loads(json.dumps(stats, default=str))
            assert rows[0].computed_at is not None

            # Calling again upserts (still one row), no duplicate/error.
            await service.refresh_statistics()
            count = (
                await db_session.execute(select(func.count()).select_from(NlSqlStatsCache))
            ).scalar_one()
            assert count == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_get_statistics_text_matches_freshly_computed_format():
    engine, session_factory = await _make_sqlite_session()
    try:
        async with session_factory() as db_session:
            await _seed(db_session)
            service = ColumnStatisticsService(db_session)

            computed = await service._compute_statistics()
            expected = service._format_statistics_text(computed)

            await service.refresh_statistics()
            cached_text = await service.get_statistics_text()

            assert cached_text == expected
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_get_statistics_text_first_run_falls_back_to_refresh():
    engine, session_factory = await _make_sqlite_session()
    try:
        async with session_factory() as db_session:
            await _seed(db_session)
            service = ColumnStatisticsService(db_session)

            # Cache kosong (belum pernah ingestion).
            existing = (
                await db_session.execute(select(func.count()).select_from(NlSqlStatsCache))
            ).scalar_one()
            assert existing == 0

            stats = await service.get_statistics_text()

            # Output benar dan cache terisi otomatis.
            assert "kpi_master_records.category" in stats
            assert "unique=['KPI Sales']" in stats
            filled = (
                await db_session.execute(select(func.count()).select_from(NlSqlStatsCache))
            ).scalar_one()
            assert filled == 1
    finally:
        await engine.dispose()
