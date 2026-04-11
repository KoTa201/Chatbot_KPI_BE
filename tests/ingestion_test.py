"""
tests/test_kpiTracker.py
Unit test untuk controller, service, dan schema KPI Tracker.

Jalankan:
    pytest tests/test_kpiTracker.py -v
    pytest tests/test_kpiTracker.py -v --tb=short
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import AsyncSession

from controller.kpiTrackerController import kpiTrackerController
from schema.kpiTrackerSchema import (
    BulkIngestionResponse,
    IngestAllSheetsRequest,
    SheetIngestionResult,
    SheetMeta,
)

# ---------------------------------------------------------------------------
# Fixtures & constants
# ---------------------------------------------------------------------------

SHEET_URL = "https://docs.google.com/spreadsheets/d/FAKE_ID/edit"

MOCK_SHEET_RESULT = SheetIngestionResult(
    log_id=1,
    sheet_name="Januari",
    meta=SheetMeta(nama_orang="PIRMADI S", bulan="Januari",
                   bulan_num=1, tahun=2025),
    total_rows=6,
    ingested=6,
    failed=0,
    errors=[],
    status="success",
)

MOCK_BULK_RESPONSE = BulkIngestionResponse(
    spreadsheet_url=SHEET_URL,
    total_sheets_processed=1,
    grand_total_rows=6,
    grand_ingested=6,
    grand_failed=0,
    overall_status="success",
    sheets=[MOCK_SHEET_RESULT],
)


def make_db() -> AsyncMock:
    return AsyncMock(spec=AsyncSession)


def make_request(**overrides) -> IngestAllSheetsRequest:
    defaults = dict(
        sheet_url=SHEET_URL,
        nama_orang_override=None,
        skip_on_error=True,
    )
    return IngestAllSheetsRequest(**{**defaults, **overrides})


# ---------------------------------------------------------------------------
# 1. kpiTrackerController — ingest_all_sheets_from_google_sheets
# ---------------------------------------------------------------------------

class TestIngestAllSheets:

    @pytest.mark.asyncio
    async def test_all_sheets_success(self):
        """Delegates ke ingestion_service dan mengembalikan BulkIngestionResponse."""
        db = make_db()
        controller = kpiTrackerController(db)
        controller.ingestion_service.ingest_all_sheets = AsyncMock(
            return_value=MOCK_BULK_RESPONSE
        )

        request = make_request()
        result = await controller.ingest_all_sheets_from_google_sheets(request)

        controller.ingestion_service.ingest_all_sheets.assert_awaited_once_with(
            sheet_url=SHEET_URL,
            nama_orang_override=None,
            skip_on_error=True,
        )
        assert result.overall_status == "success"
        assert result.grand_ingested == 6
        assert result.grand_failed == 0
        assert result.total_sheets_processed == 1
        assert result.sheets[0].status == "success"

    @pytest.mark.asyncio
    async def test_sheet_skipped_on_error(self):
        """Sheet dengan error di-skip → status skipped di response."""
        db = make_db()
        controller = kpiTrackerController(db)

        skipped_response = BulkIngestionResponse(
            spreadsheet_url=SHEET_URL,
            total_sheets_processed=1,
            grand_total_rows=0,
            grand_ingested=0,
            grand_failed=0,
            overall_status="success",
            sheets=[
                SheetIngestionResult(
                    sheet_name="Januari",
                    status="skipped",
                    reason="Sheet kosong.",
                )
            ],
        )
        controller.ingestion_service.ingest_all_sheets = AsyncMock(
            return_value=skipped_response
        )

        result = await controller.ingest_all_sheets_from_google_sheets(
            make_request(skip_on_error=True)
        )

        assert result.total_sheets_processed == 1
        assert result.sheets[0].status == "skipped"
        assert result.sheets[0].reason == "Sheet kosong."
        assert result.grand_ingested == 0

    @pytest.mark.asyncio
    async def test_nama_orang_override_diteruskan(self):
        """nama_orang_override diteruskan ke ingestion_service."""
        db = make_db()
        controller = kpiTrackerController(db)
        controller.ingestion_service.ingest_all_sheets = AsyncMock(
            return_value=MOCK_BULK_RESPONSE
        )

        await controller.ingest_all_sheets_from_google_sheets(
            make_request(nama_orang_override="OVERRIDE NAME")
        )

        controller.ingestion_service.ingest_all_sheets.assert_awaited_once_with(
            sheet_url=SHEET_URL,
            nama_orang_override="OVERRIDE NAME",
            skip_on_error=True,
        )

    @pytest.mark.asyncio
    async def test_partial_status_ketika_ada_error_rows(self):
        """Ada baris gagal → status partial pada sheet terkait."""
        db = make_db()
        controller = kpiTrackerController(db)

        partial_response = BulkIngestionResponse(
            spreadsheet_url=SHEET_URL,
            total_sheets_processed=1,
            grand_total_rows=6,
            grand_ingested=5,
            grand_failed=1,
            overall_status="partial",
            sheets=[
                SheetIngestionResult(
                    log_id=1,
                    sheet_name="Januari",
                    total_rows=6,
                    ingested=5,
                    failed=1,
                    errors=["row 3 invalid"],
                    status="partial",
                )
            ],
        )
        controller.ingestion_service.ingest_all_sheets = AsyncMock(
            return_value=partial_response
        )

        result = await controller.ingest_all_sheets_from_google_sheets(make_request())

        assert result.sheets[0].status == "partial"
        assert result.grand_failed == 1

    @pytest.mark.asyncio
    async def test_multi_sheet_grand_total(self):
        """Grand total diagregasi dari beberapa sheet."""
        db = make_db()
        controller = kpiTrackerController(db)

        multi_response = BulkIngestionResponse(
            spreadsheet_url=SHEET_URL,
            total_sheets_processed=2,
            grand_total_rows=12,
            grand_ingested=12,
            grand_failed=0,
            overall_status="success",
            sheets=[
                SheetIngestionResult(
                    log_id=1, sheet_name="Januari",
                    total_rows=6, ingested=6, failed=0, errors=[], status="success",
                ),
                SheetIngestionResult(
                    log_id=2, sheet_name="Februari",
                    total_rows=6, ingested=6, failed=0, errors=[], status="success",
                ),
            ],
        )
        controller.ingestion_service.ingest_all_sheets = AsyncMock(
            return_value=multi_response
        )

        result = await controller.ingest_all_sheets_from_google_sheets(make_request())

        assert result.total_sheets_processed == 2
        assert result.grand_ingested == 12
        assert result.grand_total_rows == 12


# ---------------------------------------------------------------------------
# 2. kpiTrackerController — get_ingestion_logs
# ---------------------------------------------------------------------------

class TestGetIngestionLogs:

    @pytest.mark.asyncio
    async def test_returns_formatted_logs(self):
        """get_ingestion_logs memformat hasil repo menjadi dict."""
        db = make_db()
        controller = kpiTrackerController(db)

        mock_log = MagicMock(
            id=1,
            sheet_name="Januari",
            nama_orang="PIRMADI S",
            total_rows=6,
            ingested_count=6,
            failed_count=0,
            status="success",
            source_type="kpi_tracker",
            created_at="2025-01-01T00:00:00",
        )
        controller.repo.get_ingestion_logs = AsyncMock(return_value=[mock_log])

        result = await controller.get_ingestion_logs(limit=20)

        assert result["total"] == 1
        assert result["logs"][0]["sheet_name"] == "Januari"
        assert result["logs"][0]["ingested"] == 6
        assert result["logs"][0]["source_type"] == "kpi_tracker"

    @pytest.mark.asyncio
    async def test_source_type_filter_diteruskan(self):
        """source_type filter diteruskan ke repo."""
        db = make_db()
        controller = kpiTrackerController(db)
        controller.repo.get_ingestion_logs = AsyncMock(return_value=[])

        await controller.get_ingestion_logs(limit=10, source_type="kpi_master")

        controller.repo.get_ingestion_logs.assert_awaited_once_with(
            10, source_type="kpi_master"
        )


# ---------------------------------------------------------------------------
# 3. kpiTrackerController — bulk_create_records
# ---------------------------------------------------------------------------

class TestBulkCreateRecords:

    @pytest.mark.asyncio
    async def test_bulk_create_success(self):
        """bulk_create_records meneruskan ke service dan return BulkCreateResponse."""
        from schema.kpiTrackerSchema import BulkCreateKPIRecordsRequest, CreateKPIRecordRequest

        db = make_db()
        controller = kpiTrackerController(db)
        controller.service.bulk_create_records = AsyncMock(return_value={
            "status": "success",
            "count": 2,
            "message": "2 records created",
        })

        request = BulkCreateKPIRecordsRequest(records=[
            CreateKPIRecordRequest(nama_kpi="KPI A", tahun=2025),
            CreateKPIRecordRequest(nama_kpi="KPI B", tahun=2025),
        ])

        result = await controller.bulk_create_records(request)

        assert result.status == "success"
        assert result.count == 2


# ---------------------------------------------------------------------------
# 4. kpiTrackerController — READ operations
# ---------------------------------------------------------------------------

class TestReadOperations:

    @pytest.mark.asyncio
    async def test_get_records_count(self):
        db = make_db()
        controller = kpiTrackerController(db)
        controller.service.get_records_count = AsyncMock(
            return_value={"total": 42})

        result = await controller.get_records_count()

        assert result.total == 42

    @pytest.mark.asyncio
    async def test_get_all_records_with_filters(self):
        db = make_db()
        controller = kpiTrackerController(db)
        controller.service.get_all_records = AsyncMock(return_value={
            "records": [],
            "pagination": {"skip": 0, "limit": 100, "total": 0, "has_more": False},
        })

        result = await controller.get_all_records(
            nama_kpi="KPI A", tahun=2025, nama_orang="Budi", skip=0, limit=100
        )

        controller.service.get_all_records.assert_awaited_once_with(
            nama_kpi="KPI A", tahun=2025, nama_orang="Budi", skip=0, limit=100
        )
        assert result.pagination.total == 0

    @pytest.mark.asyncio
    async def test_get_grouped_records(self):
        db = make_db()
        controller = kpiTrackerController(db)
        controller.service.get_grouped_records = AsyncMock(return_value={
            "groups": [],
            "pagination": {"skip": 0, "limit": 100, "total": 0, "has_more": False},
        })

        result = await controller.get_grouped_records(skip=0, limit=100)

        assert result.groups == []

    @pytest.mark.asyncio
    async def test_get_grouped_records_with_filters(self):
        db = make_db()
        controller = kpiTrackerController(db)
        controller.service.get_grouped_records_with_filters = AsyncMock(return_value={
            "groups": [],
            "pagination": {"skip": 0, "limit": 100, "total": 0, "has_more": False},
        })

        await controller.get_grouped_records_with_filters(
            tahun=2025, nama_orang="Budi", skip=0, limit=100
        )

        controller.service.get_grouped_records_with_filters.assert_awaited_once_with(
            tahun=2025, nama_orang="Budi", skip=0, limit=100
        )


# ---------------------------------------------------------------------------
# 5. kpiTrackerController — UPDATE / DELETE operations
# ---------------------------------------------------------------------------

class TestWriteOperations:

    @pytest.mark.asyncio
    async def test_update_record(self):
        from uuid import uuid4
        from schema.kpiTrackerSchema import UpdateKPIRecordRequest

        db = make_db()
        controller = kpiTrackerController(db)

        mock_record = MagicMock()
        mock_record.id = uuid4()
        mock_record.nama_kpi = "KPI Updated"
        controller.service.update_record = AsyncMock(return_value=mock_record)

        record_id = mock_record.id
        request = UpdateKPIRecordRequest(nama_kpi="KPI Updated")

        with patch(
            "controller.kpiTrackerController.KPIRecordResponse.from_orm",
            return_value=MagicMock(nama_kpi="KPI Updated"),
        ):
            result = await controller.update_record(record_id, request)

        controller.service.update_record.assert_awaited_once_with(
            record_id, {"nama_kpi": "KPI Updated"}
        )
        assert result.nama_kpi == "KPI Updated"

    @pytest.mark.asyncio
    async def test_delete_record(self):
        from uuid import uuid4

        db = make_db()
        controller = kpiTrackerController(db)
        controller.service.delete_record = AsyncMock(
            return_value={"message": "Record deleted"}
        )

        result = await controller.delete_record(uuid4())

        assert result.message == "Record deleted"

    @pytest.mark.asyncio
    async def test_delete_records_by_ids(self):
        from uuid import uuid4
        from schema.kpiTrackerSchema import BulkDeleteKPIRecordsRequest

        db = make_db()
        controller = kpiTrackerController(db)
        controller.service.delete_records_by_ids = AsyncMock(return_value={
            "status": "success",
            "count": 2,
            "message": "2 records deleted",
        })

        ids = [uuid4(), uuid4()]
        request = BulkDeleteKPIRecordsRequest(record_ids=ids)
        result = await controller.delete_records_by_ids(request)

        controller.service.delete_records_by_ids.assert_awaited_once_with(ids)
        assert result.count == 2


# ---------------------------------------------------------------------------
# 6. Schema — validasi Pydantic
# ---------------------------------------------------------------------------

class TestSchemas:

    def test_bulk_ingestion_response_valid(self):
        resp = BulkIngestionResponse(
            spreadsheet_url=SHEET_URL,
            total_sheets_processed=2,
            grand_total_rows=10,
            grand_ingested=10,
            grand_failed=0,
            overall_status="success",
            sheets=[
                SheetIngestionResult(sheet_name="Januari", status="success"),
                SheetIngestionResult(
                    sheet_name="Februari", status="skipped", reason="Sheet kosong."
                ),
            ],
        )
        assert resp.overall_status == "success"
        assert resp.sheets[1].reason == "Sheet kosong."

    def test_sheet_ingestion_result_optional_fields(self):
        r = SheetIngestionResult(sheet_name="Maret", status="skipped")
        assert r.log_id is None
        assert r.meta is None
        assert r.errors is None

    def test_sheet_meta_all_optional(self):
        m = SheetMeta(nama_orang=None, bulan=None, bulan_num=None, tahun=None)
        assert m.tahun is None

    def test_ingest_all_sheets_request_defaults(self):
        req = IngestAllSheetsRequest(sheet_url=SHEET_URL, tahun=2025)
        assert req.skip_on_error is True
        assert req.nama_orang_override is None

    def test_ingest_all_sheets_request_override(self):
        req = IngestAllSheetsRequest(
            sheet_url=SHEET_URL,
            tahun=2025,
            nama_orang_override="Budi",
            skip_on_error=False,
        )
        assert req.nama_orang_override == "Budi"
        assert req.skip_on_error is False


# ---------------------------------------------------------------------------
# 7. Repository — create_ingestion_log with source_type
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_ingestion_log_with_source_type():
    """create_ingestion_log menyimpan source_type dengan benar."""
    from repository.ingestionLogRepository import IngestionLogRepository

    db = AsyncMock(spec=AsyncSession)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    with patch.object(db, "add") as mock_add:
        repo = IngestionLogRepository(db)
        await repo.create_ingestion_log(
            sheet_url="https://docs.google.com/spreadsheets/d/X",
            spreadsheet_id="X",
            sheet_name="Sheet1",
            nama_orang=None,
            total_rows=5,
            ingested_count=5,
            errors=[],
            status="success",
            source_type="kpi_master",
        )
        call_args = mock_add.call_args[0][0]
        assert call_args.source_type == "kpi_master"
