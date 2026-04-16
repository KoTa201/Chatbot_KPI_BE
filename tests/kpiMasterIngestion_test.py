"""
tests/kpiMasterIngestion_test.py
Unit tests untuk KPI Master ingestion dari Google Sheets.

Strategi:
  - Mock Google Sheets API responses (fetch_sheet)
  - Mock repository operations (upsert, get_or_create)
  - Test error handling (malformed data, network errors, validation)
  - Test IngestionLog creation dan status updates
  - Test KPIGroup auto-creation (trigger-like behavior)

Cara menjalankan:
    pytest tests/kpiMasterIngestion_test.py -v
"""

import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from service.kpiMasterIngestionService import KPIMasterIngestionService


# ─────────────────────────────────────────────────────────────────────────────
# Konstanta
# ─────────────────────────────────────────────────────────────────────────────

SHEET_URL = "https://docs.google.com/spreadsheets/d/1abc123/edit"
SPREADSHEET_ID = "1abc123"
SHEET_NAME = "KPI"
TAHUN = 2025
GROUP_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
LOG_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")

# Modul tempat objek digunakan
_KPI_REPO = "service.kpiMasterIngestionService.KPIMasterRepository"
_KPI_SVC = "service.kpiMasterIngestionService.KPIMasterService"
_LOG_REPO = "service.kpiMasterIngestionService.IngestionLogRepository"
_GROUP_REPO = "service.kpiMasterIngestionService.KPIGroupRepository"
_GOOGLE_SVC = "service.kpiMasterIngestionService.GoogleSheetService"


# ─────────────────────────────────────────────────────────────────────────────
# Mock Builders
# ─────────────────────────────────────────────────────────────────────────────

def make_db() -> AsyncMock:
    """Create mock AsyncSession."""
    return AsyncMock(spec=AsyncSession)


def make_kpi_group(
    *,
    id: uuid.UUID = GROUP_ID,
    sheet_id: str = SPREADSHEET_ID,
    group_type: str = "master",
    nama_grup: str = "KPI Master 2025",
    sheet_url: str = SHEET_URL,
    sheet_name: str = SHEET_NAME,
    tahun: int = TAHUN,
    is_active: bool = True,
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
    group.is_active = is_active
    group.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    group.updated_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    group.master_records = []
    return group


def make_ingestion_log(
    *,
    id: uuid.UUID = LOG_ID,
    kpi_group_id: uuid.UUID = GROUP_ID,
    status: str = "running",
    total_rows: int = 0,
    ingested_count: int = 0,
    failed_count: int = 0,
    errors: str | None = None,
):
    """Create mock IngestionLogORM."""
    log = MagicMock()
    log.id = id
    log.kpi_group_id = kpi_group_id
    log.status = status
    log.total_rows = total_rows
    log.ingested_count = ingested_count
    log.failed_count = failed_count
    log.errors = errors
    log.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    log.updated_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return log


def make_sample_records(count: int = 3) -> list[dict]:
    """Create sample KPI Master records for testing."""
    return [
        {
            "tahun": TAHUN,
            "category": "Operasional",
            "kpi_name": f"KPI Master {i}",
            "definisi_operasional": f"Definition {i}",
            "target": "90%",
            "achieve": "85%",
            "partial": "80%",
            "fail": "50%",
            "responsibility_persons": "Manager A",
        }
        for i in range(1, count + 1)
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Tests: Happy Path
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ingest_kpi_master_success():
    """Successful KPI Master ingestion."""
    # Setup mocks
    kpi_repo = AsyncMock()
    kpi_service = AsyncMock()
    log_repo = AsyncMock()
    group_repo = AsyncMock()

    service = KPIMasterIngestionService(
        kpi_repo, kpi_service, log_repo, group_repo)

    # Mock dependencies
    import pandas as pd
    mock_df = pd.DataFrame([
        {"col1": "KPI1", "col2": "def1"},
        {"col1": "KPI2", "col2": "def2"},
    ])

    mock_group = make_kpi_group()
    mock_log = make_ingestion_log()
    sample_records = make_sample_records(2)

    group_repo.get_or_create = AsyncMock(return_value=mock_group)
    log_repo.create = AsyncMock(return_value=mock_log)
    kpi_repo.upsert_by_group = AsyncMock(return_value=2)
    log_repo.update_status = AsyncMock()

    with (
        patch("service.kpiMasterIngestionService.GoogleSheetService"),
        patch.object(service, "_fetch_sheet", return_value=(
            mock_df, SPREADSHEET_ID, SHEET_NAME)),
        patch.object(service, "_parse", return_value=(sample_records, [])),
        patch.object(service, "_resolve_status", return_value="success"),
        patch.object(service, "_format_errors", return_value=None),
    ):
        # Execute
        result = await service.ingest_kpi_master(SHEET_URL, TAHUN)

        # Verify
        assert result["status"] == "success"
        assert result["count"] == 2
        assert str(result["group_id"]) == str(GROUP_ID)
        assert str(result["log_id"]) == str(LOG_ID)

        # Verify group creation
        group_repo.get_or_create.assert_called_once()
        call_kwargs = group_repo.get_or_create.call_args.kwargs
        assert call_kwargs["sheet_id"] == SPREADSHEET_ID
        assert call_kwargs["group_type"] == "master"

        # Verify log creation
        log_repo.create.assert_called_once_with(kpi_group_id=GROUP_ID)

        # Verify upsert
        kpi_repo.upsert_by_group.assert_called_once()
        upsert_records = kpi_repo.upsert_by_group.call_args[0][0]
        assert all(r["group_id"] == GROUP_ID for r in upsert_records)


@pytest.mark.asyncio
async def test_ingest_kpi_master_partial_success():
    """KPI Master ingestion with some errors."""
    # Setup
    kpi_repo = AsyncMock()
    kpi_service = AsyncMock()
    log_repo = AsyncMock()
    group_repo = AsyncMock()

    service = KPIMasterIngestionService(
        kpi_repo, kpi_service, log_repo, group_repo)

    mock_group = make_kpi_group()
    mock_log = make_ingestion_log()
    sample_records = make_sample_records(3)
    errors = ["Row 5: Missing required field 'kpi_name'"]

    import pandas as pd
    mock_df = pd.DataFrame()

    group_repo.get_or_create = AsyncMock(return_value=mock_group)
    log_repo.create = AsyncMock(return_value=mock_log)
    kpi_repo.upsert_by_group = AsyncMock(return_value=3)
    log_repo.update_status = AsyncMock()

    with (
        patch("service.kpiMasterIngestionService.GoogleSheetService"),
        patch.object(service, "_fetch_sheet", return_value=(
            mock_df, SPREADSHEET_ID, SHEET_NAME)),
        patch.object(service, "_parse", return_value=(sample_records, errors)),
        patch.object(service, "_resolve_status", return_value="partial"),
        patch.object(service, "_format_errors",
                     return_value="1 errors during parsing"),
    ):
        result = await service.ingest_kpi_master(SHEET_URL, TAHUN)

        assert result["status"] == "partial"
        assert result["count"] == 3
        log_repo.update_status.assert_called_once()
        call_kwargs = log_repo.update_status.call_args.kwargs
        assert call_kwargs["status"] == "partial"


# ─────────────────────────────────────────────────────────────────────────────
# Tests: Error Handling
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ingest_kpi_master_no_valid_records():
    """Ingestion fails when no valid records found after parsing."""
    kpi_repo = AsyncMock()
    kpi_service = AsyncMock()
    log_repo = AsyncMock()
    group_repo = AsyncMock()

    service = KPIMasterIngestionService(
        kpi_repo, kpi_service, log_repo, group_repo)

    mock_group = make_kpi_group()
    mock_log = make_ingestion_log()

    import pandas as pd
    mock_df = pd.DataFrame()

    group_repo.get_or_create = AsyncMock(return_value=mock_group)
    log_repo.create = AsyncMock(return_value=mock_log)
    log_repo.update_status = AsyncMock()

    with (
        patch.object(service, "_fetch_sheet", return_value=(
            mock_df, SPREADSHEET_ID, SHEET_NAME)),
        patch.object(service, "_parse", return_value=(
            [], ["All rows invalid"])),
        patch.object(service, "_mark_log_failed", new_callable=AsyncMock),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await service.ingest_kpi_master(SHEET_URL, TAHUN)

        assert exc_info.value.status_code == 422
        assert "tidak menghasilkan records valid" in exc_info.value.detail.lower()

        # Log should be marked as failed
        log_repo.update_status.assert_called_once()
        call_kwargs = log_repo.update_status.call_args.kwargs
        assert call_kwargs["status"] == "failed"


@pytest.mark.asyncio
async def test_ingest_kpi_master_sheet_fetch_error():
    """Ingestion fails when Google Sheets fetch fails."""
    kpi_repo = AsyncMock()
    kpi_service = AsyncMock()
    log_repo = AsyncMock()
    group_repo = AsyncMock()

    service = KPIMasterIngestionService(
        kpi_repo, kpi_service, log_repo, group_repo)

    with patch.object(service, "_fetch_sheet", side_effect=HTTPException(
        status_code=404, detail="Sheet not found"
    )):
        with pytest.raises(HTTPException) as exc_info:
            await service.ingest_kpi_master(SHEET_URL, TAHUN)

        assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_ingest_kpi_master_unexpected_error_updates_log():
    """Unexpected error during ingestion updates log to failed."""
    kpi_repo = AsyncMock()
    kpi_service = AsyncMock()
    log_repo = AsyncMock()
    group_repo = AsyncMock()

    service = KPIMasterIngestionService(
        kpi_repo, kpi_service, log_repo, group_repo)

    mock_group = make_kpi_group()
    mock_log = make_ingestion_log()

    import pandas as pd
    mock_df = pd.DataFrame()

    group_repo.get_or_create = AsyncMock(return_value=mock_group)
    log_repo.create = AsyncMock(return_value=mock_log)
    log_repo.update_status = AsyncMock()

    with (
        patch.object(service, "_fetch_sheet", return_value=(
            mock_df, SPREADSHEET_ID, SHEET_NAME)),
        patch.object(service, "_parse", side_effect=Exception(
            "Unexpected parsing error")),
        patch.object(service, "_mark_log_failed", new_callable=AsyncMock),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await service.ingest_kpi_master(SHEET_URL, TAHUN)

        assert exc_info.value.status_code == 500


# ─────────────────────────────────────────────────────────────────────────────
# Tests: KPIGroup Auto-Creation
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ingest_creates_kpi_group_if_not_exists():
    """Ingestion creates KPIGroup if sheet_id not seen before."""
    kpi_repo = AsyncMock()
    kpi_service = AsyncMock()
    log_repo = AsyncMock()
    group_repo = AsyncMock()

    service = KPIMasterIngestionService(
        kpi_repo, kpi_service, log_repo, group_repo)

    mock_group = make_kpi_group()
    mock_log = make_ingestion_log()
    sample_records = make_sample_records(1)

    import pandas as pd
    mock_df = pd.DataFrame()

    group_repo.get_or_create = AsyncMock(return_value=mock_group)
    log_repo.create = AsyncMock(return_value=mock_log)
    kpi_repo.upsert_by_group = AsyncMock(return_value=1)
    log_repo.update_status = AsyncMock()

    with (
        patch("service.kpiMasterIngestionService.GoogleSheetService"),
        patch.object(service, "_fetch_sheet", return_value=(
            mock_df, SPREADSHEET_ID, SHEET_NAME)),
        patch.object(service, "_parse", return_value=(sample_records, [])),
        patch.object(service, "_resolve_status", return_value="success"),
        patch.object(service, "_format_errors", return_value=None),
    ):
        result = await service.ingest_kpi_master(SHEET_URL, TAHUN)

        # Verify group creation called with correct params
        group_repo.get_or_create.assert_called_once()
        call_kwargs = group_repo.get_or_create.call_args.kwargs
        assert call_kwargs["sheet_id"] == SPREADSHEET_ID
        assert call_kwargs["sheet_url"] == SHEET_URL
        assert call_kwargs["group_type"] == "master"


@pytest.mark.asyncio
async def test_ingest_upserts_existing_kpi_group():
    """Re-ingesting same sheet updates existing KPIGroup."""
    kpi_repo = AsyncMock()
    kpi_service = AsyncMock()
    log_repo = AsyncMock()
    group_repo = AsyncMock()

    service = KPIMasterIngestionService(
        kpi_repo, kpi_service, log_repo, group_repo)

    # Simulate existing group
    existing_group = make_kpi_group(
        sheet_url="https://old-url/spreadsheets/d/1abc123/edit"
    )
    mock_log = make_ingestion_log()
    sample_records = make_sample_records(2)

    import pandas as pd
    mock_df = pd.DataFrame()

    # get_or_create returns existing group after update
    group_repo.get_or_create = AsyncMock(return_value=existing_group)
    log_repo.create = AsyncMock(return_value=mock_log)
    kpi_repo.upsert_by_group = AsyncMock(return_value=2)
    log_repo.update_status = AsyncMock()

    with (
        patch("service.kpiMasterIngestionService.GoogleSheetService"),
        patch.object(service, "_fetch_sheet", return_value=(
            mock_df, SPREADSHEET_ID, SHEET_NAME)),
        patch.object(service, "_parse", return_value=(sample_records, [])),
        patch.object(service, "_resolve_status", return_value="success"),
        patch.object(service, "_format_errors", return_value=None),
    ):
        result = await service.ingest_kpi_master(SHEET_URL, TAHUN)

        # verify get_or_create was called (upsert behavior)
        group_repo.get_or_create.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# Tests: IngestionLog Lifecycle
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ingestion_log_created_before_processing():
    """IngestionLog created with status='running' before processing."""
    kpi_repo = AsyncMock()
    kpi_service = AsyncMock()
    log_repo = AsyncMock()
    group_repo = AsyncMock()

    service = KPIMasterIngestionService(
        kpi_repo, kpi_service, log_repo, group_repo)

    mock_group = make_kpi_group()
    mock_log = make_ingestion_log(status="running")
    sample_records = make_sample_records(1)

    import pandas as pd
    mock_df = pd.DataFrame()

    group_repo.get_or_create = AsyncMock(return_value=mock_group)
    log_repo.create = AsyncMock(return_value=mock_log)
    kpi_repo.upsert_by_group = AsyncMock(return_value=1)
    log_repo.update_status = AsyncMock()

    with (
        patch("service.kpiMasterIngestionService.GoogleSheetService"),
        patch.object(service, "_fetch_sheet", return_value=(
            mock_df, SPREADSHEET_ID, SHEET_NAME)),
        patch.object(service, "_parse", return_value=(sample_records, [])),
        patch.object(service, "_resolve_status", return_value="success"),
        patch.object(service, "_format_errors", return_value=None),
    ):
        await service.ingest_kpi_master(SHEET_URL, TAHUN)

        # Log should be created with group_id
        log_repo.create.assert_called_once_with(kpi_group_id=GROUP_ID)


@pytest.mark.asyncio
async def test_ingestion_log_updated_on_completion():
    """IngestionLog updated with final status and counts."""
    kpi_repo = AsyncMock()
    kpi_service = AsyncMock()
    log_repo = AsyncMock()
    group_repo = AsyncMock()

    service = KPIMasterIngestionService(
        kpi_repo, kpi_service, log_repo, group_repo)

    mock_group = make_kpi_group()
    mock_log = make_ingestion_log()
    sample_records = make_sample_records(5)

    import pandas as pd
    mock_df = pd.DataFrame()

    group_repo.get_or_create = AsyncMock(return_value=mock_group)
    log_repo.create = AsyncMock(return_value=mock_log)
    kpi_repo.upsert_by_group = AsyncMock(return_value=5)
    log_repo.update_status = AsyncMock()

    with (
        patch("service.kpiMasterIngestionService.GoogleSheetService"),
        patch.object(service, "_fetch_sheet", return_value=(
            mock_df, SPREADSHEET_ID, SHEET_NAME)),
        patch.object(service, "_parse", return_value=(sample_records, [])),
        patch.object(service, "_resolve_status", return_value="success"),
        patch.object(service, "_format_errors", return_value=None),
    ):
        await service.ingest_kpi_master(SHEET_URL, TAHUN)

        # update_status should be called with correct values
        log_repo.update_status.assert_called_once()
        call_kwargs = log_repo.update_status.call_args.kwargs
        assert call_kwargs["status"] == "success"
        assert call_kwargs["total_rows"] == 5
        assert call_kwargs["ingested_count"] == 5
        assert call_kwargs["failed_count"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# Tests: Data Injection
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ingest_injects_group_id_into_records():
    """Each record receives group_id before upsert."""
    kpi_repo = AsyncMock()
    kpi_service = AsyncMock()
    log_repo = AsyncMock()
    group_repo = AsyncMock()

    service = KPIMasterIngestionService(
        kpi_repo, kpi_service, log_repo, group_repo)

    mock_group = make_kpi_group()
    mock_log = make_ingestion_log()
    sample_records = make_sample_records(3)

    import pandas as pd
    mock_df = pd.DataFrame()

    group_repo.get_or_create = AsyncMock(return_value=mock_group)
    log_repo.create = AsyncMock(return_value=mock_log)
    kpi_repo.upsert_by_group = AsyncMock(return_value=3)
    log_repo.update_status = AsyncMock()

    with (
        patch("service.kpiMasterIngestionService.GoogleSheetService"),
        patch.object(service, "_fetch_sheet", return_value=(
            mock_df, SPREADSHEET_ID, SHEET_NAME)),
        patch.object(service, "_parse", return_value=(sample_records, [])),
        patch.object(service, "_resolve_status", return_value="success"),
        patch.object(service, "_format_errors", return_value=None),
    ):
        await service.ingest_kpi_master(SHEET_URL, TAHUN)

        # Verify all injected records contain group_id
        upsert_call = kpi_repo.upsert_by_group.call_args[0]
        records_with_group = upsert_call[0]
        assert len(records_with_group) == 3
        assert all(r["group_id"] == GROUP_ID for r in records_with_group)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
