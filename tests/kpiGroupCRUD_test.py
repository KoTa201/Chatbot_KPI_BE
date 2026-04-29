"""
tests/kpiGroupCRUD_test.py
Unit tests untuk KPI Group CRUD operations.

Coverage:
  - CREATE: create_group() with auto-fetch dari Google Sheets
  - READ:   list_groups() dengan pagination, filter, search
  - READ:   get_group() dengan related records
  - UPDATE: update_group() dengan conditional re-ingestion
  - DELETE: delete_group()

Strategi mocking:
  - Mock KPIGroupRepository dan service dependencies
  - Mock GoogleSheetService untuk ekstrak sheet info
  - Mock ingestion services untuk re-ingestion saat sheet_url berubah

Cara menjalankan:
    pytest tests/kpiGroupCRUD_test.py -v
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from service.kpiGroupService import KPIGroupService
from schema.kpiGroupSchema import (
    KPIGroupCreate,
    KPIGroupUpdate,
    KPIGroupResponse,
)


# ─────────────────────────────────────────────────────────────────────────────
# Konstanta
# ─────────────────────────────────────────────────────────────────────────────

GROUP_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
SHEET_URL = "https://docs.google.com/spreadsheets/d/1abc123/edit"
SPREADSHEET_ID = "1abc123"
SHEET_NAME = "KPI Sheet"
TAHUN = 2025

# Modul tempat repository digunakan
_REPO = "service.kpiGroupService.KPIGroupRepository"
_GOOGLE_SVC = "service.kpiGroupService.GoogleSheetService"


# ─────────────────────────────────────────────────────────────────────────────
# Mock Builders
# ─────────────────────────────────────────────────────────────────────────────

def make_db() -> AsyncMock:
    """Create mock AsyncSession."""
    db = AsyncMock(spec=AsyncSession)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


def make_kpi_group(
    *,
    id: uuid.UUID = GROUP_ID,
    sheet_id: str = SPREADSHEET_ID,
    group_type: str = "master",
    nama_grup: str = "KPI Group A",
    sheet_url: str = SHEET_URL,
    sheet_name: str = SHEET_NAME,
    tahun: int | None = TAHUN,
    is_scheduled: bool = True,
    is_active: bool = True,
    master_records: list = None,
    tracker_records: list = None,
):
    """Create mock KPIGroupORM."""
    group = MagicMock()
    group.id = id
    group.sheet_id = sheet_id
    group.group_type = group_type
    group.nama_grup = nama_grup
    group.sheet_url = sheet_url
    group.sheet_name = sheet_name
    group.tahun = tahun
    group.is_scheduled = is_scheduled
    group.is_active = is_active
    group.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    group.updated_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    group.master_records = master_records or []
    group.tracker_records = tracker_records or []
    return group


def make_master_record(
    *,
    id: uuid.UUID = uuid.uuid4(),
    group_id: uuid.UUID = GROUP_ID,
    kpi_name: str = "KPI A",
    category: str = "Operasional",
    tahun: int = TAHUN,
):
    """Create mock KPIMasterORM."""
    record = MagicMock()
    record.id = id
    record.group_id = group_id
    record.kpi_name = kpi_name
    record.category = category
    record.tahun = tahun
    record.definisi_operasional = "Definition"
    record.target = "90%"
    record.achieve = "85%"
    record.partial = "80%"
    record.fail = "50%"
    record.responsibility_persons = "Manager A"
    record.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return record


# ─────────────────────────────────────────────────────────────────────────────
# Tests: CREATE
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_kpi_group_master_with_explicit_sheet_info():
    """Create KPI Group master dengan sheet_id dan nama_grup yang diberikan."""
    db = make_db()
    service = KPIGroupService(db)

    payload = KPIGroupCreate(
        sheet_url=SHEET_URL,
        sheet_id=SPREADSHEET_ID,
        sheet_name=SHEET_NAME,
        nama_grup="KPI Master 2025",
        group_type="master",
        tahun=TAHUN,
        is_scheduled=True,
        is_active=True,
    )

    mock_group = make_kpi_group(nama_grup="KPI Master 2025")

    with patch.object(
        service.repo, "get_or_create",
        new_callable=AsyncMock, return_value=mock_group
    ):
        result = await service.create_group(payload)

        assert result.nama_grup == "KPI Master 2025"
        assert result.group_type == "master"
        assert result.is_active is True
        service.repo.get_or_create.assert_called_once()
        call_kwargs = service.repo.get_or_create.call_args.kwargs
        assert call_kwargs["sheet_id"] == SPREADSHEET_ID
        assert call_kwargs["nama_grup"] == "KPI Master 2025"


@pytest.mark.asyncio
async def test_create_kpi_group_auto_fetch_sheet_info():
    """Create KPI Group auto-fetch sheet_id dan nama dari Google Sheets jika tidak diberikan."""
    db = make_db()
    service = KPIGroupService(db)

    payload = KPIGroupCreate(
        sheet_url=SHEET_URL,
        sheet_id=None,  # Will be auto-fetched
        sheet_name=None,
        nama_grup=None,  # Will be auto-fetched
        group_type="master",
        tahun=TAHUN,
    )

    mock_group = make_kpi_group(
        nama_grup="Auto-fetched Sheet Name",
        sheet_id=SPREADSHEET_ID,
    )

    with (
        patch.object(
            service.repo, "get_or_create",
            new_callable=AsyncMock, return_value=mock_group
        ),
        patch("service.kpiGroupService.GoogleSheetService") as mock_google_class,
    ):
        mock_google = MagicMock()
        mock_google.get_spreadsheet_title.return_value = "Auto-fetched Sheet Name"
        mock_google_class.return_value = mock_google

        result = await service.create_group(payload)

        # Verify auto-fetch was attempted
        assert result.nama_grup == "Auto-fetched Sheet Name"
        service.repo.get_or_create.assert_called_once()


@pytest.mark.asyncio
async def test_create_kpi_group_tracker():
    """Create KPI Group dengan group_type=tracker."""
    db = make_db()
    service = KPIGroupService(db)

    payload = KPIGroupCreate(
        sheet_url=SHEET_URL,
        sheet_id=SPREADSHEET_ID,
        sheet_name="Tracker",
        nama_grup="KPI Tracker 2025",
        group_type="tracker",
        is_scheduled=False,
        is_active=True,
    )

    mock_group = make_kpi_group(
        group_type="tracker",
        nama_grup="KPI Tracker 2025",
    )

    with patch.object(
        service.repo, "get_or_create",
        new_callable=AsyncMock, return_value=mock_group
    ):
        result = await service.create_group(payload)

        assert result.group_type == "tracker"
        assert result.nama_grup == "KPI Tracker 2025"


# ─────────────────────────────────────────────────────────────────────────────
# Tests: READ (List)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_kpi_groups_all():
    """List semua KPI Groups dengan pagination."""
    db = make_db()
    service = KPIGroupService(db)

    groups = [
        make_kpi_group(
            id=uuid.UUID(f"1111111{i}-1111-1111-1111-111111111111"),
            nama_grup=f"Group {i}",
        )
        for i in range(3)
    ]

    with patch.object(
        service.repo, "list_groups",
        new_callable=AsyncMock, return_value=(groups, 3)
    ):
        result = await service.list_groups(page=1, limit=10)

        assert result.total == 3
        assert result.page == 1
        assert result.limit == 10
        assert len(result.data) == 3
        service.repo.list_groups.assert_called_once()
        call_kwargs = service.repo.list_groups.call_args.kwargs
        assert call_kwargs["page"] == 1
        assert call_kwargs["limit"] == 10
        assert call_kwargs["tahun"] is None
        assert call_kwargs["group_type"] is None
        assert call_kwargs["search"] is None


@pytest.mark.asyncio
async def test_list_kpi_groups_with_filter():
    """List KPI Groups dengan filter group_type."""
    db = make_db()
    service = KPIGroupService(db)

    master_groups = [
        make_kpi_group(
            id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
            group_type="master",
        ),
    ]

    with patch.object(
        service.repo, "list_groups",
        new_callable=AsyncMock, return_value=(master_groups, 1)
    ):
        result = await service.list_groups(
            page=1,
            limit=10,
            group_type="master",
        )

        assert result.total == 1
        assert all(g.group_type == "master" for g in result.data)
        call_kwargs = service.repo.list_groups.call_args.kwargs
        assert call_kwargs["tahun"] is None
        assert call_kwargs["group_type"] == "master"


@pytest.mark.asyncio
async def test_list_kpi_groups_with_search():
    """List KPI Groups dengan search keyword."""
    db = make_db()
    service = KPIGroupService(db)

    matching_groups = [
        make_kpi_group(
            nama_grup="KPI Master 2025",
        ),
    ]

    with patch.object(
        service.repo, "list_groups",
        new_callable=AsyncMock, return_value=(matching_groups, 1)
    ):
        result = await service.list_groups(
            page=1,
            limit=10,
            search="KPI Master",
        )

        assert result.total == 1
        call_kwargs = service.repo.list_groups.call_args.kwargs
        assert call_kwargs["tahun"] is None
        assert call_kwargs["search"] == "KPI Master"


@pytest.mark.asyncio
async def test_list_kpi_groups_with_tahun_filter():
    """List KPI Groups dengan filter tahun."""
    db = make_db()
    service = KPIGroupService(db)

    groups_2025 = [
        make_kpi_group(
            nama_grup="KPI Group 2025",
            tahun=2025,
        ),
    ]

    with patch.object(
        service.repo, "list_groups",
        new_callable=AsyncMock, return_value=(groups_2025, 1)
    ):
        result = await service.list_groups(
            page=1,
            limit=10,
            tahun=2025,
        )

        assert result.total == 1
        call_kwargs = service.repo.list_groups.call_args.kwargs
        assert call_kwargs["tahun"] == 2025


@pytest.mark.asyncio
async def test_list_kpi_groups_pagination():
    """List KPI Groups dengan pagination calculation."""
    db = make_db()
    service = KPIGroupService(db)

    groups = [make_kpi_group() for _ in range(5)]

    with patch.object(
        service.repo, "list_groups",
        new_callable=AsyncMock, return_value=(groups, 25)
    ):
        result = await service.list_groups(page=1, limit=5)

        assert result.total == 25
        assert result.total_pages == 5


# ─────────────────────────────────────────────────────────────────────────────
# Tests: READ (Get One)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_kpi_group_by_id():
    """Get satu KPI Group dengan all related records."""
    db = make_db()
    service = KPIGroupService(db)

    mock_records = [
        make_master_record(kpi_name=f"KPI {i}")
        for i in range(2)
    ]
    mock_group = make_kpi_group(
        master_records=mock_records,
    )

    with patch.object(
        service.repo, "get_by_id",
        new_callable=AsyncMock, return_value=mock_group
    ):
        result = await service.get_group(GROUP_ID)

        assert result.id == GROUP_ID
        assert result.nama_grup == "KPI Group A"
        assert len(result.master_records) == 2
        service.repo.get_by_id.assert_called_once_with(GROUP_ID)


@pytest.mark.asyncio
async def test_get_kpi_group_not_found():
    """Get KPI Group dengan ID yang tidak ada."""
    db = make_db()
    service = KPIGroupService(db)

    not_found_id = uuid.UUID("99999999-9999-9999-9999-999999999999")

    with patch.object(
        service.repo, "get_by_id",
        new_callable=AsyncMock, return_value=None
    ):
        with pytest.raises(HTTPException) as exc_info:
            await service.get_group(not_found_id)

        assert exc_info.value.status_code == 404
        assert "tidak ditemukan" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_get_kpi_group_master_with_records():
    """Get master KPI Group dengan all master records."""
    db = make_db()
    service = KPIGroupService(db)

    master_records = [
        make_master_record(kpi_name="KPI A"),
        make_master_record(kpi_name="KPI B"),
    ]
    mock_group = make_kpi_group(
        group_type="master",
        master_records=master_records,
    )

    with patch.object(
        service.repo, "get_by_id",
        new_callable=AsyncMock, return_value=mock_group
    ):
        result = await service.get_group(GROUP_ID)

        assert result.group_type == "master"
        assert len(result.master_records) == 2
        assert result.master_records[0].kpi_name == "KPI A"


# ─────────────────────────────────────────────────────────────────────────────
# Tests: UPDATE
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_kpi_group_partial():
    """Update beberapa field pada KPI Group."""
    db = make_db()
    service = KPIGroupService(db)

    original_group = make_kpi_group(
        nama_grup="Old Name",
        is_active=True,
    )
    updated_group = make_kpi_group(
        nama_grup="New Name",
        is_active=False,
    )

    payload = KPIGroupUpdate(
        nama_grup="New Name",
        is_active=False,
    )

    with (
        patch.object(
            service.repo, "get_by_id",
            new_callable=AsyncMock, return_value=original_group
        ),
        patch.object(
            service.repo, "update",
            new_callable=AsyncMock, return_value=updated_group
        ),
    ):
        result = await service.update_group(GROUP_ID, payload)

        assert result.nama_grup == "New Name"
        assert result.is_active is False
        service.repo.update.assert_called_once()
        call_kwargs = service.repo.update.call_args.kwargs
        assert call_kwargs["group_id"] == GROUP_ID


@pytest.mark.asyncio
async def test_update_kpi_group_sheet_url_triggers_re_ingestion_master():
    """Update sheet_url pada master group triggers KPI Master re-ingestion."""
    db = make_db()
    service = KPIGroupService(db)

    original_group = make_kpi_group(
        group_type="master",
        sheet_url=SHEET_URL,
    )
    new_sheet_url = "https://docs.google.com/spreadsheets/d/2xyz789/edit"
    updated_group = make_kpi_group(
        group_type="master",
        sheet_url=new_sheet_url,
    )

    payload = KPIGroupUpdate(
        sheet_url=new_sheet_url,
        tahun=TAHUN,
    )

    with (
        patch.object(
            service.repo, "get_by_id",
            new_callable=AsyncMock, return_value=original_group
        ),
        patch.object(
            service.repo, "update",
            new_callable=AsyncMock, return_value=updated_group
        ),
        patch(
            "service.kpiGroupService.KPIMasterIngestionService"
        ) as mock_ingest_class,
    ):
        mock_ingest_svc = AsyncMock()
        mock_ingest_class.return_value = mock_ingest_svc

        result = await service.update_group(GROUP_ID, payload)

        # Verify re-ingestion triggered
        assert str(result.sheet_url) == new_sheet_url
        mock_ingest_svc.update_and_reingest.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_kpi_group_tahun_triggers_re_ingestion_master():
    """Update tahun pada master group triggers KPI Master re-ingestion."""
    db = make_db()
    service = KPIGroupService(db)

    original_group = make_kpi_group(
        group_type="master",
        sheet_url=SHEET_URL,
        tahun=TAHUN,
    )
    updated_group = make_kpi_group(
        group_type="master",
        sheet_url=SHEET_URL,
        tahun=2026,
    )

    payload = KPIGroupUpdate(
        tahun=2026,
    )

    with (
        patch.object(
            service.repo, "get_by_id",
            new_callable=AsyncMock, return_value=original_group
        ),
        patch.object(
            service.repo, "update",
            new_callable=AsyncMock, return_value=updated_group
        ),
        patch(
            "service.kpiGroupService.KPIMasterIngestionService"
        ) as mock_ingest_class,
    ):
        mock_ingest_svc = AsyncMock()
        mock_ingest_class.return_value = mock_ingest_svc

        result = await service.update_group(GROUP_ID, payload)

        assert result.tahun == 2026
        mock_ingest_svc.update_and_reingest.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_kpi_group_sheet_url_triggers_re_ingestion_tracker():
    """Update sheet_url pada tracker group triggers Tracker re-ingestion."""
    db = make_db()
    service = KPIGroupService(db)

    original_group = make_kpi_group(
        group_type="tracker",
        sheet_url=SHEET_URL,
    )
    new_sheet_url = "https://docs.google.com/spreadsheets/d/2xyz789/edit"
    updated_group = make_kpi_group(
        group_type="tracker",
        sheet_url=new_sheet_url,
    )

    payload = KPIGroupUpdate(
        sheet_url=new_sheet_url,
        tahun=2026,
    )

    with (
        patch.object(
            service.repo, "get_by_id",
            new_callable=AsyncMock, return_value=original_group
        ),
        patch.object(
            service.repo, "update",
            new_callable=AsyncMock, return_value=updated_group
        ),
        patch(
            "service.kpiGroupService.TrackerIngestionService"
        ) as mock_ingest_class,
    ):
        mock_ingest_svc = AsyncMock()
        mock_ingest_class.return_value = mock_ingest_svc

        result = await service.update_group(GROUP_ID, payload)

        assert str(result.sheet_url) == new_sheet_url


@pytest.mark.asyncio
async def test_update_kpi_group_master_requires_tahun_when_sheet_url_changes():
    """Update sheet_url pada master group HARUS disertai tahun."""
    db = make_db()
    service = KPIGroupService(db)

    original_group = make_kpi_group(
        group_type="master",
        tahun=2025,
    )

    payload = KPIGroupUpdate(
        sheet_url="https://new-sheet-url",
        tahun=None,  # Missing!
    )

    with patch.object(
        service.repo, "get_by_id",
        new_callable=AsyncMock, return_value=original_group
    ):
        with pytest.raises(HTTPException) as exc_info:
            await service.update_group(GROUP_ID, payload)

        assert exc_info.value.status_code == 400
        assert "tahun" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_update_kpi_group_not_found():
    """Update KPI Group dengan ID yang tidak ada."""
    db = make_db()
    service = KPIGroupService(db)

    not_found_id = uuid.UUID("99999999-9999-9999-9999-999999999999")

    payload = KPIGroupUpdate(
        nama_grup="New Name",
    )

    with patch.object(
        service.repo, "get_by_id",
        new_callable=AsyncMock, return_value=None
    ):
        with pytest.raises(HTTPException) as exc_info:
            await service.update_group(not_found_id, payload)

        assert exc_info.value.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# Tests: DELETE
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_kpi_group():
    """Delete KPI Group by ID."""
    db = make_db()
    service = KPIGroupService(db)

    with patch.object(
        service.repo, "delete",
        new_callable=AsyncMock,
    ):
        result = await service.delete_group(GROUP_ID)

        assert "berhasil dihapus" in result["message"].lower()
        service.repo.delete.assert_called_once_with(GROUP_ID)
        db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_delete_kpi_group_commits_transaction():
    """Delete operation commits transaction."""
    db = make_db()
    service = KPIGroupService(db)

    with patch.object(
        service.repo, "delete",
        new_callable=AsyncMock,
    ):
        await service.delete_group(GROUP_ID)

        # Verify transaction committed
        db.commit.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# Tests: Response Building
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_build_response_excludes_records_for_list():
    """_build_response without include_records=True returns empty record lists."""
    db = make_db()
    service = KPIGroupService(db)

    records = [make_master_record() for _ in range(3)]
    group = make_kpi_group(master_records=records)

    response = service._build_response(group, include_records=False)

    assert len(response.master_records) == 0
    assert len(response.tracker_records) == 0


@pytest.mark.asyncio
async def test_build_response_includes_master_records():
    """_build_response includes master_records when include_records=True."""
    db = make_db()
    service = KPIGroupService(db)

    records = [
        make_master_record(kpi_name="KPI 1"),
        make_master_record(kpi_name="KPI 2"),
    ]
    group = make_kpi_group(
        group_type="master",
        master_records=records,
    )

    response = service._build_response(group, include_records=True)

    assert len(response.master_records) == 2
    assert response.master_records[0].kpi_name == "KPI 1"


@pytest.mark.asyncio
async def test_build_response_fields_match_orm():
    """_build_response correctly maps all ORM fields to response."""
    db = make_db()
    service = KPIGroupService(db)

    group = make_kpi_group(
        nama_grup="Test Group",
        group_type="master",
        sheet_url=SHEET_URL,
        sheet_id=SPREADSHEET_ID,
        tahun=TAHUN,
        is_scheduled=True,
        is_active=False,
    )

    response = service._build_response(group)

    assert response.id == GROUP_ID
    assert response.nama_grup == "Test Group"
    assert response.group_type == "master"
    assert str(response.sheet_url) == SHEET_URL
    assert response.sheet_id == SPREADSHEET_ID
    assert response.tahun == TAHUN
    assert response.is_scheduled is True
    assert response.is_active is False


# ─────────────────────────────────────────────────────────────────────────────
# Tests: Integration Scenarios
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_list_get_delete_flow():
    """Complete CRUD flow: create → list → get → delete."""
    db = make_db()
    service = KPIGroupService(db)

    # CREATE
    create_payload = KPIGroupCreate(
        sheet_url=SHEET_URL,
        sheet_id=SPREADSHEET_ID,
        sheet_name=SHEET_NAME,
        nama_grup="New Group",
        group_type="master",
        tahun=TAHUN,
    )

    mock_group = make_kpi_group(nama_grup="New Group")

    with patch.object(
        service.repo, "get_or_create",
        new_callable=AsyncMock, return_value=mock_group
    ):
        created = await service.create_group(create_payload)
        assert created.nama_grup == "New Group"

    # LIST
    with patch.object(
        service.repo, "list_groups",
        new_callable=AsyncMock, return_value=([mock_group], 1)
    ):
        listed = await service.list_groups(page=1, limit=10)
        assert listed.total == 1

    # GET
    with patch.object(
        service.repo, "get_by_id",
        new_callable=AsyncMock, return_value=mock_group
    ):
        fetched = await service.get_group(GROUP_ID)
        assert fetched.id == GROUP_ID

    # DELETE
    with patch.object(
        service.repo, "delete",
        new_callable=AsyncMock,
    ):
        result = await service.delete_group(GROUP_ID)
        assert "berhasil dihapus" in result["message"].lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
