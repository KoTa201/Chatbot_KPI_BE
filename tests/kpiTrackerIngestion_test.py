"""
tests/kpiTrackerIngestion_test.py
Unit tests untuk ingestion KPI Tracker.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from schema.kpiTrackerSchema import TrackerSourceItem
from service.TrackeringestionService import TrackerIngestionService


SHEET_URL = "https://docs.google.com/spreadsheets/d/tracker123/edit"
SPREADSHEET_ID = "tracker123"
SHEET_NAME = "JANUARI 2026"
GROUP_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")
LOG_ID = uuid.UUID("55555555-5555-5555-5555-555555555555")
MASTER_ID = uuid.UUID("66666666-6666-6666-6666-666666666666")
USER_ID = uuid.UUID("77777777-7777-7777-7777-777777777777")
TAHUN = 2026


def make_service():
    """Create Tracker ingestion service dengan dependency yang dimock."""
    db = AsyncMock(spec=AsyncSession)
    tracker_repo = AsyncMock()
    log_repo = AsyncMock()
    group_repo = AsyncMock()
    service = TrackerIngestionService(
        db=db,
        tracker_repo=tracker_repo,
        log_repo=log_repo,
        group_repo=group_repo,
    )
    return service, db, tracker_repo, log_repo, group_repo


def make_group():
    group = MagicMock()
    group.id = GROUP_ID
    group.nama_grup = "KPI Tracker 2026"
    return group


def make_log():
    log = MagicMock()
    log.id = LOG_ID
    return log


def make_sheet():
    return {
        "sheet_index": 0,
        "sheet_name": SHEET_NAME,
        "sheet_id": 123,
        "spreadsheet_id": SPREADSHEET_ID,
        "df": [{"row": 1}, {"row": 2}],
        "meta": {
            "nama_orang": "Budi Santoso",
            "bulan_num": 1,
            "tahun": TAHUN,
        },
        "error": None,
    }


@pytest.mark.asyncio
async def test_ingest_all_sheets_tracker_success_inserts_clean_records_and_updates_log():
    """Ingestion KPI Tracker sukses harus match master, resolve user, insert records, dan update log success."""
    service, _db, tracker_repo, log_repo, group_repo = make_service()
    group_repo.get_or_create.return_value = make_group()
    log_repo.create.return_value = make_log()
    tracker_repo.delete_kpi_records_by_group_and_period.return_value = 0
    tracker_repo.bulk_insert_kpi_records.return_value = 2
    service.google_svc.get_spreadsheet_title = MagicMock(return_value="KPI Tracker 2026")

    parsed_records = [
        {
            "nama_kpi": "Revenue Growth",
            "nama_orang": "Budi Santoso",
            "tahun": TAHUN,
            "realisasi": "10%",
            "keterangan": "On track",
            "source_sheet_id": SPREADSHEET_ID,
            "source_sheet_name": SHEET_NAME,
        },
        {
            "nama_kpi": "Revenue Growth",
            "nama_orang": "Budi Santoso",
            "tahun": TAHUN,
            "realisasi": "12%",
            "keterangan": None,
            "source_sheet_id": SPREADSHEET_ID,
            "source_sheet_name": SHEET_NAME,
        },
    ]

    mock_lookup = MagicMock()
    mock_lookup.preload = AsyncMock()
    mock_lookup.stats.return_value = {"users": 1}
    mock_lookup.by_full_name = AsyncMock(return_value=USER_ID)

    with (
        patch.object(service, "_fetch_all_sheets", return_value=[make_sheet()]),
        patch.object(service, "_parse_records", return_value=(parsed_records, [])),
        patch.object(service, "_resolve_kpi_master_ids", new_callable=AsyncMock, return_value={"Revenue Growth": MASTER_ID}),
        patch("service.TrackeringestionService.UserLookupUtil", return_value=mock_lookup),
    ):
        result = await service.ingest_all_sheets(
            sheet_url=SHEET_URL,
            tahun=TAHUN,
            skip_on_error=True,
        )

    assert result["overall_status"] == "success"
    assert result["total_sheets_processed"] == 1
    assert result["grand_total_rows"] == 2
    assert result["grand_ingested"] == 2
    assert result["grand_failed"] == 0
    assert result["sheets"][0]["status"] == "success"

    group_repo.get_or_create.assert_awaited_once_with(
        sheet_id=SPREADSHEET_ID,
        group_type="tracker",
        sheet_url=SHEET_URL,
        sheet_name=None,
        nama_grup="KPI Tracker 2026",
        tahun=TAHUN,
    )
    log_repo.create.assert_awaited_once_with(
        kpi_group_id=GROUP_ID,
        source_type="tracker",
        group_name="KPI Tracker 2026",
    )
    tracker_repo.delete_kpi_records_by_group_and_period.assert_awaited_once_with(
        group_id=GROUP_ID,
        tahun=TAHUN,
        bulan_num=1,
    )
    tracker_repo.bulk_insert_kpi_records.assert_awaited_once()

    clean_records = tracker_repo.bulk_insert_kpi_records.await_args.args[0]
    assert clean_records[0]["group_id"] == GROUP_ID
    assert clean_records[0]["kpi_master_id"] == MASTER_ID
    assert clean_records[0]["user_id"] == USER_ID
    assert clean_records[0]["bulan_num"] == 1
    assert "nama_kpi" not in clean_records[0]
    assert "nama_orang" not in clean_records[0]
    assert "source_sheet_name" not in clean_records[0]

    log_repo.update_status.assert_awaited_once_with(
        log_id=LOG_ID,
        status="success",
        total_rows=2,
        ingested_count=2,
        failed_count=0,
        errors=None,
    )


@pytest.mark.asyncio
async def test_ingest_all_sheets_tracker_fails_when_kpi_master_not_found():
    """Ingestion KPI Tracker harus gagal per sheet jika nama KPI tidak match ke KPI Master."""
    service, _db, tracker_repo, log_repo, group_repo = make_service()
    group_repo.get_or_create.return_value = make_group()
    log_repo.create.return_value = make_log()
    service.google_svc.get_spreadsheet_title = MagicMock(return_value="KPI Tracker 2026")

    parsed_records = [
        {
            "nama_kpi": "KPI Tidak Ada",
            "nama_orang": "Budi Santoso",
            "tahun": TAHUN,
            "realisasi": "10%",
        }
    ]

    mock_lookup = MagicMock()
    mock_lookup.preload = AsyncMock()
    mock_lookup.stats.return_value = {"users": 1}

    with (
        patch.object(service, "_fetch_all_sheets", return_value=[make_sheet()]),
        patch.object(service, "_parse_records", return_value=(parsed_records, [])),
        patch.object(service, "_resolve_kpi_master_ids", new_callable=AsyncMock, return_value={}),
        patch("service.TrackeringestionService.UserLookupUtil", return_value=mock_lookup),
    ):
        result = await service.ingest_all_sheets(sheet_url=SHEET_URL, tahun=TAHUN)

    assert result["overall_status"] == "failed"
    assert result["grand_ingested"] == 0
    assert result["grand_failed"] == 2
    assert result["sheets"][0]["status"] == "failed"
    assert "KPI 'KPI Tidak Ada' tidak ditemukan di kpi_master_records" in result["sheets"][0]["errors"]
    tracker_repo.bulk_insert_kpi_records.assert_not_awaited()

    update_kwargs = log_repo.update_status.await_args.kwargs
    assert update_kwargs["status"] == "failed"
    assert update_kwargs["total_rows"] == 2
    assert update_kwargs["ingested_count"] == 0
    assert update_kwargs["failed_count"] == 2


@pytest.mark.asyncio
async def test_ingest_batch_tracker_continues_when_one_source_fails():
    """Batch ingestion Tracker harus tetap memproses source lain ketika satu source gagal."""
    service, _db, _tracker_repo, _log_repo, _group_repo = make_service()
    sources = [
        TrackerSourceItem(sheet_url="https://docs.google.com/spreadsheets/d/ok/edit", tahun=TAHUN),
        TrackerSourceItem(sheet_url="https://docs.google.com/spreadsheets/d/bad/edit", tahun=TAHUN),
    ]

    async def ingest_side_effect(sheet_url, tahun, skip_on_error):
        if "bad" in sheet_url:
            raise RuntimeError("spreadsheet tidak bisa dibaca")
        return {
            "spreadsheet_url": sheet_url,
            "total_sheets_processed": 1,
            "grand_total_rows": 2,
            "grand_ingested": 2,
            "grand_failed": 0,
            "overall_status": "success",
            "sheets": [],
        }

    with patch.object(
        service,
        "ingest_all_sheets",
        new_callable=AsyncMock,
        side_effect=ingest_side_effect,
    ):
        result = await service.ingest_batch(
            sources=sources,
            skip_on_error=True,
            delay_between_sources=0.0,
        )

    assert result["total_urls"] == 2
    assert result["succeeded"] == 1
    assert result["failed"] == 1
    assert result["grand_total_rows"] == 2
    assert result["grand_ingested"] == 2
    assert result["results"][0]["status"] == "success"
    assert result["results"][1]["status"] == "error"
    assert "spreadsheet tidak bisa dibaca" in result["results"][1]["error"]
