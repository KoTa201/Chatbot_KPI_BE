"""
tests/kpiMasterIngestion_test.py
Unit tests untuk ingestion KPI Master.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from exceptions import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from service.kpiMasterIngestionService import KPIMasterIngestionService


SHEET_URL = "https://docs.google.com/spreadsheets/d/master123/edit"
SPREADSHEET_ID = "master123"
SHEET_NAME = "KPI Master"
GROUP_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
LOG_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
USER_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
TAHUN = 2026


def make_service():
    """Create KPI Master ingestion service dengan dependency yang dimock."""
    db = AsyncMock(spec=AsyncSession)
    kpi_repo = AsyncMock()
    kpi_service = AsyncMock()
    log_repo = AsyncMock()
    group_repo = AsyncMock()
    service = KPIMasterIngestionService(
        db=db,
        kpi_repo=kpi_repo,
        kpi_service=kpi_service,
        log_repo=log_repo,
        group_repo=group_repo,
    )
    return service, db, kpi_repo, log_repo, group_repo


def make_group():
    group = MagicMock()
    group.id = GROUP_ID
    group.nama_grup = f"{SHEET_NAME} Master {TAHUN}"
    return group


def make_log():
    log = MagicMock()
    log.id = LOG_ID
    return log


@pytest.mark.asyncio
async def test_ingest_kpi_master_success_upserts_group_records_and_log():
    """Ingestion KPI Master sukses harus upsert KPIGroup, records, dan update log success."""
    service, _db, kpi_repo, log_repo, group_repo = make_service()
    group_repo.get_or_create.return_value = make_group()
    log_repo.create.return_value = make_log()
    kpi_repo.upsert_by_group.return_value = 2

    parsed_records = [
        {
            "tahun": TAHUN,
            "kpi_name": "Revenue Growth",
            "category": "Financial",
            "responsibility_persons": "Budi Santoso",
        },
        {
            "tahun": TAHUN,
            "kpi_name": "Customer Satisfaction",
            "category": "Service",
            "responsibility_persons": "Sari Dewi",
        },
    ]

    async def inject_user_ids(records):
        for record in records:
            record.pop("responsibility_persons", None)
            record["user_ids"] = [USER_ID]
        return records, []

    with (
        patch.object(service, "_fetch_sheet", return_value=(object(), SPREADSHEET_ID, SHEET_NAME)),
        patch.object(service, "_parse", return_value=(parsed_records, [])),
        patch.object(service, "_inject_user_ids", new_callable=AsyncMock, side_effect=inject_user_ids),
    ):
        result = await service.ingest_kpi_master(sheet_url=SHEET_URL, tahun=TAHUN)

    assert result["status"] == "success"
    assert result["count"] == 2
    assert result["group_id"] == str(GROUP_ID)
    assert result["log_id"] == str(LOG_ID)
    assert result["unresolved_users"] == []

    group_repo.get_or_create.assert_awaited_once_with(
        sheet_id=SPREADSHEET_ID,
        group_type="master",
        sheet_url=SHEET_URL,
        sheet_name=SHEET_NAME,
        nama_grup=f"{SHEET_NAME} Master {TAHUN}",
        tahun=TAHUN,
    )
    log_repo.create.assert_awaited_once_with(
        kpi_group_id=GROUP_ID,
        source_type="master",
    )
    kpi_repo.upsert_by_group.assert_awaited_once()

    records_for_upsert = kpi_repo.upsert_by_group.await_args.args[0]
    assert all(record["group_id"] == GROUP_ID for record in records_for_upsert)
    assert all(record["user_ids"] == [USER_ID] for record in records_for_upsert)
    assert "responsibility_persons" not in records_for_upsert[0]

    log_repo.update_status.assert_any_await(
        log_id=LOG_ID,
        status="success",
        total_rows=2,
        ingested_count=2,
        failed_count=0,
        errors=None,
    )


@pytest.mark.asyncio
async def test_ingest_kpi_master_fails_when_pic_user_unresolved():
    """Ingestion KPI Master harus gagal 422 jika PIC di sheet tidak ditemukan di tabel users."""
    service, _db, kpi_repo, log_repo, group_repo = make_service()
    group_repo.get_or_create.return_value = make_group()
    log_repo.create.return_value = make_log()

    parsed_records = [
        {
            "tahun": TAHUN,
            "kpi_name": "Revenue Growth",
            "category": "Financial",
            "responsibility_persons": "User Tidak Ada",
        }
    ]

    with (
        patch.object(service, "_fetch_sheet", return_value=(object(), SPREADSHEET_ID, SHEET_NAME)),
        patch.object(service, "_parse", return_value=(parsed_records, [])),
        patch.object(
            service,
            "_inject_user_ids",
            new_callable=AsyncMock,
            return_value=(parsed_records, ["User Tidak Ada"]),
        ),
    ):
        with pytest.raises(ValidationError) as exc_info:
            await service.ingest_kpi_master(sheet_url=SHEET_URL, tahun=TAHUN)

    assert exc_info.value.status_code == 422
    assert "User tidak ditemukan untuk: User Tidak Ada" in exc_info.value.message
    kpi_repo.upsert_by_group.assert_not_awaited()

    failed_updates = [
        call.kwargs for call in log_repo.update_status.await_args_list
        if call.kwargs.get("status") == "failed"
    ]
    assert failed_updates
    assert "User Tidak Ada" in failed_updates[0]["errors"]


@pytest.mark.asyncio
async def test_ingest_kpi_master_fails_when_parser_returns_no_valid_records():
    """Ingestion KPI Master harus gagal 422 jika parser tidak menghasilkan record valid."""
    service, _db, kpi_repo, log_repo, group_repo = make_service()
    group_repo.get_or_create.return_value = make_group()
    log_repo.create.return_value = make_log()

    with (
        patch.object(service, "_fetch_sheet", return_value=(object(), SPREADSHEET_ID, SHEET_NAME)),
        patch.object(service, "_parse", return_value=([], ["Baris 2 invalid"])),
    ):
        with pytest.raises(ValidationError) as exc_info:
            await service.ingest_kpi_master(sheet_url=SHEET_URL, tahun=TAHUN)

    assert exc_info.value.status_code == 422
    assert exc_info.value.message == "Sheet tidak menghasilkan records valid."
    kpi_repo.upsert_by_group.assert_not_awaited()
    log_repo.update_status.assert_any_await(
        log_id=LOG_ID,
        status="failed",
        total_rows=0,
        ingested_count=0,
        errors="Tidak ada records valid setelah parsing.",
    )
