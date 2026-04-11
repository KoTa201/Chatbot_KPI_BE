"""
tests/test_kpiMaster.py
Unit tests for KPI Master controller, service, schema, parser, dan repository.

Run:
    pytest tests/test_kpiMaster.py -v
    pytest tests/test_kpiMaster.py -v --tb=short
"""

import pandas as pd
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import AsyncSession

from controller.kpiMasterController import KPIMasterController
from schema.kpiMasterSchema import (
    DetailMastersResponse,
    GroupedKPIMasterResponse,
    IngestionResponse,
    IngestKPIMasterRequest,
    KPIMasterResponse,
)
from utils.kpiMasterParser import parse_kpi_master_dataframe

# ---------------------------------------------------------------------------
# Helpers & constants
# ---------------------------------------------------------------------------

SHEET_URL = "https://docs.google.com/spreadsheets/d/FAKE_ID/edit"
SPREADSHEET_ID = "FAKE_ID"
SHEET_NAME = "Sheet1"
TAHUN = 2024

MOCK_RECORDS = [
    {
        "tahun": TAHUN,
        "category": "KPI High Level",
        "kpi_name": "Revenue Achievement",
        "definisi_operasional": None,
        "dihitung": None,
        "tidak_dihitung": None,
        "rumus": None,
        "target": "20 M",
        "sumber_data": None,
        "achieve": "≥100%",
        "partial": "85–99%",
        "fail": "<85%",
        "responsibility_persons": "Pirmadi S",
        "source_sheet_id": SPREADSHEET_ID,
        "source_sheet_name": SHEET_NAME,
    }
]
MOCK_ERRORS: list = []


def make_db() -> AsyncMock:
    return AsyncMock(spec=AsyncSession)


def make_request(**overrides) -> IngestKPIMasterRequest:
    defaults = dict(sheet_url=SHEET_URL, tahun=TAHUN)
    return IngestKPIMasterRequest(**{**defaults, **overrides})


def make_pagination(total: int = 0) -> dict:
    return {"skip": 0, "limit": 100, "total": total, "has_more": False}


# ---------------------------------------------------------------------------
# 1. Parser — parse_kpi_master_dataframe
# ---------------------------------------------------------------------------

def _make_df(rows: list[list]) -> pd.DataFrame:
    return pd.DataFrame(rows)


HEADER_ROW = [
    "KPI", "Definisi Operasional", "Dihitung", "Tidak Dihitung", "Rumus",
    "Target", "Sumber Data", "Achieve", "Partial", "Fail", "Responsobility Persons",
]
DATA_ROW = [
    "Revenue Achievement", "Total nilai PO signed", "Semua PO", "Forecast",
    "Total PO ÷ Target", "20 M", "Finance", "≥100%", "85–99%", "<85%",
    "Pirmadi S, Djoko K",
]


class TestParser:

    def test_extracts_category_and_records(self):
        rows = [
            ["KPI High Level"] + [None] * 10,
            HEADER_ROW,
            DATA_ROW,
        ]
        records, errors = parse_kpi_master_dataframe(
            _make_df(rows), SPREADSHEET_ID, SHEET_NAME, tahun=TAHUN)
        assert len(records) == 1
        assert records[0]["category"] == "KPI High Level"
        assert records[0]["kpi_name"] == "Revenue Achievement"
        assert records[0]["target"] == "20 M"
        assert records[0]["responsibility_persons"] == "Pirmadi S, Djoko K"
        assert errors == []

    def test_skips_blank_rows_between_sections(self):
        rows = [
            ["KPI High Level"] + [None] * 10,
            HEADER_ROW,
            ["Revenue Achievement", "Desc", "A", "B", "C", "20 M",
                "Finance", "≥100%", "85–99%", "<85%", "Pirmadi S"],
            [None] * 11,
            ["KPI Product Management"] + [None] * 10,
            HEADER_ROW,
            ["Product Launch", "Desc", "A", "B", "C", "3",
                "Product doc", "≥100%", "67–99%", "<67%", "Erlan H"],
        ]
        records, errors = parse_kpi_master_dataframe(
            _make_df(rows), SPREADSHEET_ID, SHEET_NAME, tahun=TAHUN)
        assert len(records) == 2
        assert records[0]["category"] == "KPI High Level"
        assert records[1]["category"] == "KPI Product Management"

    def test_empty_sheet_returns_empty_with_error(self):
        records, errors = parse_kpi_master_dataframe(
            _make_df([]), SPREADSHEET_ID, SHEET_NAME, tahun=TAHUN)
        assert records == []
        assert len(errors) == 1
        assert "empty" in errors[0].lower()

    def test_normalizes_responsibility_persons(self):
        rows = [
            ["KPI High Level"] + [None] * 10,
            HEADER_ROW,
            ["Revenue Achievement", "Desc", "A", "B", "C", "20 M", "Finance",
             "≥100%", "85–99%", "<85%", "  Pirmadi S ,  Djoko K  "],
        ]
        records, _ = parse_kpi_master_dataframe(
            _make_df(rows), SPREADSHEET_ID, SHEET_NAME, tahun=TAHUN)
        assert records[0]["responsibility_persons"] == "Pirmadi S, Djoko K"

    def test_data_row_before_category_header_goes_to_errors(self):
        rows = [DATA_ROW]
        records, errors = parse_kpi_master_dataframe(
            _make_df(rows), SPREADSHEET_ID, SHEET_NAME, tahun=TAHUN)
        assert records == []
        assert len(errors) == 1

    def test_skips_row_with_empty_kpi_name(self):
        rows = [
            ["KPI High Level"] + [None] * 10,
            HEADER_ROW,
            [None, "Some desc", "A", "B", "C", "20 M", "Finance",
                "≥100%", "85–99%", "<85%", "Pirmadi S"],
        ]
        records, errors = parse_kpi_master_dataframe(
            _make_df(rows), SPREADSHEET_ID, SHEET_NAME, tahun=TAHUN)
        assert records == []
        assert len(errors) == 1

    def test_stamps_source_sheet_metadata(self):
        rows = [
            ["KPI High Level"] + [None] * 10,
            HEADER_ROW,
            DATA_ROW,
        ]
        records, _ = parse_kpi_master_dataframe(
            _make_df(rows), "MY_SHEET_ID", "MySheet", tahun=TAHUN)
        assert records[0]["source_sheet_id"] == "MY_SHEET_ID"
        assert records[0]["source_sheet_name"] == "MySheet"

    def test_stamps_tahun_on_records(self):
        rows = [
            ["KPI High Level"] + [None] * 10,
            HEADER_ROW,
            DATA_ROW,
        ]
        records, _ = parse_kpi_master_dataframe(
            _make_df(rows), SPREADSHEET_ID, SHEET_NAME, tahun=2026)
        assert records[0]["tahun"] == 2026

    def test_multiple_records_under_same_category(self):
        rows = [
            ["KPI High Level"] + [None] * 10,
            HEADER_ROW,
            ["KPI A", "Desc", "A", "B", "C", "10", "Src",
                "≥100%", "80–99%", "<80%", "Person A"],
            ["KPI B", "Desc", "A", "B", "C", "20", "Src",
                "≥100%", "80–99%", "<80%", "Person B"],
        ]
        records, errors = parse_kpi_master_dataframe(
            _make_df(rows), SPREADSHEET_ID, SHEET_NAME, tahun=TAHUN)
        assert len(records) == 2
        assert records[0]["category"] == records[1]["category"] == "KPI High Level"
        assert errors == []


# ---------------------------------------------------------------------------
# 2. KPIMasterController — ingest_kpi_master
# ---------------------------------------------------------------------------

class TestIngestKPIMaster:

    @pytest.mark.asyncio
    async def test_delegates_to_ingestion_service(self):
        """ingest_kpi_master meneruskan request ke ingestion_service."""
        db = make_db()
        controller = KPIMasterController(db)
        controller.ingestion_service.ingest_kpi_master = AsyncMock(return_value={
            "status": "success",
            "count": 1,
            "message": "1 records ingested",
        })

        result = await controller.ingest_kpi_master(make_request())

        controller.ingestion_service.ingest_kpi_master.assert_awaited_once_with(
            sheet_url=SHEET_URL,
            tahun=TAHUN,
        )
        assert isinstance(result, IngestionResponse)
        assert result.status == "success"
        assert result.count == 1

    @pytest.mark.asyncio
    async def test_returns_partial_when_errors(self):
        db = make_db()
        controller = KPIMasterController(db)
        controller.ingestion_service.ingest_kpi_master = AsyncMock(return_value={
            "status": "partial",
            "count": 0,
            "message": "0 records ingested, 1 failed",
        })

        result = await controller.ingest_kpi_master(make_request())

        assert result.status == "partial"
        assert result.count == 0

    @pytest.mark.asyncio
    async def test_returns_failed_when_all_error(self):
        db = make_db()
        controller = KPIMasterController(db)
        controller.ingestion_service.ingest_kpi_master = AsyncMock(return_value={
            "status": "failed",
            "count": 0,
            "message": "Ingestion failed",
        })

        result = await controller.ingest_kpi_master(make_request())

        assert result.status == "failed"

    @pytest.mark.asyncio
    async def test_tahun_diteruskan_ke_service(self):
        """tahun dari request diteruskan dengan benar ke service."""
        db = make_db()
        controller = KPIMasterController(db)
        controller.ingestion_service.ingest_kpi_master = AsyncMock(return_value={
            "status": "success", "count": 1, "message": "ok",
        })

        await controller.ingest_kpi_master(make_request(tahun=2026))

        controller.ingestion_service.ingest_kpi_master.assert_awaited_once_with(
            sheet_url=SHEET_URL,
            tahun=2026,
        )


# ---------------------------------------------------------------------------
# 3. KPIMasterController — preview_kpi_master
# ---------------------------------------------------------------------------

class TestPreviewKPIMaster:

    @pytest.mark.asyncio
    async def test_preview_returns_expected_keys(self):
        db = make_db()
        controller = KPIMasterController(db)

        mock_df = MagicMock()
        with (
            patch.object(
                controller, "_fetch_sheet",
                return_value=(mock_df, SPREADSHEET_ID, SHEET_NAME),
            ),
            patch(
                "utils.kpiMasterParser.parse_kpi_master_dataframe",  # ← fixed
                return_value=(MOCK_RECORDS, MOCK_ERRORS),
            ),
        ):
            result = await controller.preview_kpi_master(SHEET_URL, TAHUN)

        assert result["spreadsheet_id"] == SPREADSHEET_ID
        assert result["sheet_name"] == SHEET_NAME
        assert result["tahun"] == TAHUN
        assert result["total_records"] == 1
        assert result["errors"] == []
        assert "preview" in result
        assert result["preview"] == MOCK_RECORDS[:5]

    @pytest.mark.asyncio
    async def test_preview_limits_to_five_records(self):
        db = make_db()
        controller = KPIMasterController(db)

        many_records = [
            {**MOCK_RECORDS[0], "kpi_name": f"KPI {i}"} for i in range(10)
        ]
        mock_df = MagicMock()
        with (
            patch.object(controller, "_fetch_sheet",
                         return_value=(mock_df, SPREADSHEET_ID, SHEET_NAME)),
            patch("utils.kpiMasterParser.parse_kpi_master_dataframe",  # ← fixed
                  return_value=(many_records, [])),
        ):
            result = await controller.preview_kpi_master(SHEET_URL, TAHUN)

        assert len(result["preview"]) == 5

    @pytest.mark.asyncio
    async def test_preview_propagates_fetch_error(self):
        """HTTPException dari _fetch_sheet harus di-propagate."""
        from fastapi import HTTPException

        db = make_db()
        controller = KPIMasterController(db)

        with patch.object(
            controller, "_fetch_sheet",
            side_effect=HTTPException(status_code=422, detail="Invalid URL"),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await controller.preview_kpi_master("invalid-url", TAHUN)

        assert exc_info.value.status_code == 422


# ---------------------------------------------------------------------------
# 4. KPIMasterController — get_grouped_records
# ---------------------------------------------------------------------------

class TestGetGroupedRecords:

    @pytest.mark.asyncio
    async def test_get_grouped_records_delegates_to_service(self):
        db = make_db()
        controller = KPIMasterController(db)
        controller.service.get_grouped_records = AsyncMock(return_value={
            "groups": [],
            "pagination": make_pagination(),
        })

        result = await controller.get_grouped_records(skip=0, limit=100)

        controller.service.get_grouped_records.assert_awaited_once_with(
            skip=0, limit=100)
        assert isinstance(result, GroupedKPIMasterResponse)
        assert result.groups == []

    @pytest.mark.asyncio
    async def test_get_grouped_records_pagination_params(self):
        db = make_db()
        controller = KPIMasterController(db)
        controller.service.get_grouped_records = AsyncMock(return_value={
            "groups": [],
            "pagination": make_pagination(),
        })

        await controller.get_grouped_records(skip=10, limit=50)

        controller.service.get_grouped_records.assert_awaited_once_with(
            skip=10, limit=50)


# ---------------------------------------------------------------------------
# 5. KPIMasterController — get_grouped_records_with_filters
# ---------------------------------------------------------------------------

class TestGetGroupedRecordsWithFilters:

    @pytest.mark.asyncio
    async def test_filters_diteruskan_ke_service(self):
        db = make_db()
        controller = KPIMasterController(db)
        controller.service.get_grouped_records_with_filters = AsyncMock(return_value={
            "groups": [],
            "pagination": make_pagination(),
        })

        await controller.get_grouped_records_with_filters(
            tahun=2025, category="KPI High Level", skip=0, limit=100
        )

        controller.service.get_grouped_records_with_filters.assert_awaited_once_with(
            tahun=2025, category="KPI High Level", skip=0, limit=100
        )

    @pytest.mark.asyncio
    async def test_none_filters_diteruskan(self):
        """None filters harus diteruskan as-is ke service."""
        db = make_db()
        controller = KPIMasterController(db)
        controller.service.get_grouped_records_with_filters = AsyncMock(return_value={
            "groups": [],
            "pagination": make_pagination(),
        })

        result = await controller.get_grouped_records_with_filters(
            tahun=None, category=None, skip=0, limit=100
        )

        controller.service.get_grouped_records_with_filters.assert_awaited_once_with(
            tahun=None, category=None, skip=0, limit=100
        )
        assert isinstance(result, GroupedKPIMasterResponse)


# ---------------------------------------------------------------------------
# 6. KPIMasterController — get_detail_records_by_source_sheet_name
# ---------------------------------------------------------------------------

class TestGetDetailRecords:

    @pytest.mark.asyncio
    async def test_returns_detail_records_response(self):
        db = make_db()
        controller = KPIMasterController(db)

        mock_orm_record = MagicMock()
        controller.service.get_detail_records_by_source_sheet_name = AsyncMock(return_value={
            "source_sheet_name": SHEET_NAME,
            "records": [mock_orm_record],
            "pagination": make_pagination(total=1),
        })

        with patch(
            "controller.kpiMasterController.KPIMasterResponse.from_orm",
            return_value=MagicMock(spec=KPIMasterResponse),
        ):
            result = await controller.get_detail_records_by_source_sheet_name(
                SHEET_NAME, skip=0, limit=100
            )

        assert isinstance(result, DetailMastersResponse)
        assert result.source_sheet_name == SHEET_NAME
        assert len(result.records) == 1

    @pytest.mark.asyncio
    async def test_source_sheet_name_diteruskan(self):
        db = make_db()
        controller = KPIMasterController(db)
        controller.service.get_detail_records_by_source_sheet_name = AsyncMock(return_value={
            "source_sheet_name": "OtherSheet",
            "records": [],
            "pagination": make_pagination(),
        })

        await controller.get_detail_records_by_source_sheet_name(
            "OtherSheet", skip=5, limit=20
        )

        controller.service.get_detail_records_by_source_sheet_name.assert_awaited_once_with(
            source_sheet_name="OtherSheet", skip=5, limit=20
        )

    @pytest.mark.asyncio
    async def test_empty_records_returns_valid_response(self):
        db = make_db()
        controller = KPIMasterController(db)
        controller.service.get_detail_records_by_source_sheet_name = AsyncMock(return_value={
            "source_sheet_name": SHEET_NAME,
            "records": [],
            "pagination": make_pagination(),
        })

        result = await controller.get_detail_records_by_source_sheet_name(
            SHEET_NAME, skip=0, limit=100
        )

        assert result.records == []
        assert result.pagination.total == 0


# ---------------------------------------------------------------------------
# 7. Schema — validasi Pydantic
# ---------------------------------------------------------------------------

class TestSchemas:

    def test_ingest_request_valid(self):
        req = make_request()
        assert req.sheet_url == SHEET_URL
        assert req.tahun == TAHUN

    def test_ingest_request_tahun_out_of_range(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            IngestKPIMasterRequest(sheet_url=SHEET_URL, tahun=1999)
        with pytest.raises(ValidationError):
            IngestKPIMasterRequest(sheet_url=SHEET_URL, tahun=2032)

    def test_ingestion_response_valid(self):
        resp = IngestionResponse(
            status="success", count=5, message="5 records ingested")
        assert resp.status == "success"
        assert resp.count == 5

    def test_grouped_response_empty_groups(self):
        resp = GroupedKPIMasterResponse(
            groups=[],
            pagination={"skip": 0, "limit": 100,
                        "total": 0, "has_more": False},
        )
        assert resp.groups == []
        assert resp.pagination.total == 0

    def test_detail_masters_response_valid(self):
        resp = DetailMastersResponse(
            source_sheet_name=SHEET_NAME,
            records=[],
            pagination={"skip": 0, "limit": 100,
                        "total": 0, "has_more": False},
        )
        assert resp.source_sheet_name == SHEET_NAME
        assert resp.records == []


# ---------------------------------------------------------------------------
# 8. Repository — upsert_by_tahun
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_kpi_master_repository_upsert_by_tahun():
    """upsert_by_tahun harus mengeksekusi upsert statement dan return record count."""
    from repository.kpiMasterRepository import KPIMasterRepository

    db = make_db()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()

    repo = KPIMasterRepository(db)
    count = await repo.upsert_by_tahun(MOCK_RECORDS)

    assert count == 1
    db.execute.assert_called_once()
    db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# 9. Controller — ingest_kpi_master integration dengan _fetch_sheet & _parse
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ingest_kpi_master_delegates_via_ingestion_service():
    """ingest_kpi_master harus meneruskan ke ingestion_service, bukan langsung ke repo."""
    db = make_db()
    controller = KPIMasterController(db)
    controller.ingestion_service.ingest_kpi_master = AsyncMock(return_value={
        "status": "success",
        "count": 1,
        "message": "1 records ingested",
    })

    result = await controller.ingest_kpi_master(make_request(tahun=2024))

    controller.ingestion_service.ingest_kpi_master.assert_awaited_once_with(
        sheet_url=SHEET_URL,
        tahun=2024,
    )
    assert result.status == "success"
    assert result.count == 1
