"""
tests/test_ingestion.py
Unit test untuk endpoint & controller ingestion KPI.

Jalankan:
    pytest tests/test_ingestion.py -v
    pytest tests/test_ingestion.py -v --tb=short   # ringkas traceback
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import AsyncSession

from controller.kpiTrackerController import kpiTrackerController
from schema.ingestionSchema import BulkIngestionResponse, SheetIngestionResult, SheetMeta

# ---------------------------------------------------------------------------
# Fixtures shared
# ---------------------------------------------------------------------------

SHEET_URL = "https://docs.google.com/spreadsheets/d/FAKE_ID/edit"

MOCK_META = {
    "nama_orang": "PIRMADI S",
    "bulan": "Januari",
    "bulan_num": 1,
    "tahun": 2025,
    "header_row": 2,
}

MOCK_SHEET_ENTRY = {
    "sheet_index": 0,
    "sheet_name": "Januari",
    "sheet_id": 111,
    "spreadsheet_id": "FAKE_ID",
    "df": MagicMock(
        columns=MagicMock(tolist=MagicMock(
            return_value=["No", "Nama KPI", "Realisasi"])),
        __len__=MagicMock(return_value=6),
        head=MagicMock(return_value=MagicMock(
            fillna=MagicMock(return_value=MagicMock(
                to_dict=MagicMock(return_value=[])
            ))
        )),
    ),
    "meta": MOCK_META,
    "error": None,
}

MOCK_LOG = MagicMock(id=1)

MOCK_RECORDS = [MagicMock() for _ in range(6)]
MOCK_ERRORS: list = []


def make_db() -> AsyncMock:
    return AsyncMock(spec=AsyncSession)


# ---------------------------------------------------------------------------
# 1. kpiTrackerController — ingest_all_sheets_from_google_sheets
# ---------------------------------------------------------------------------

class TestIngestAllSheets:

    @pytest.mark.asyncio
    @patch("controller.kpiTrackerController.GoogleSheetService")
    async def test_all_sheets_success(self, MockService):
        """Semua sheet berhasil di-ingest → overall_status success."""
        mock_service = MockService.return_value
        mock_service.fetch_all_sheets_as_dataframes.return_value = [
            MOCK_SHEET_ENTRY]

        db = make_db()
        controller = kpiTrackerController(db)

        with (
            patch.object(controller, "_parse_records",
                         return_value=(MOCK_RECORDS, MOCK_ERRORS)),
            patch.object(controller.repo, "bulk_insert_kpi_records",
                         new_callable=AsyncMock, return_value=6),
            patch.object(controller.repo, "create_ingestion_log",
                         new_callable=AsyncMock, return_value=MOCK_LOG),
        ):
            result = await controller.ingest_all_sheets_from_google_sheets(
                sheet_url=SHEET_URL,
                nama_orang_override=None,
                skip_on_error=True,
            )

        assert result["overall_status"] == "success"
        assert result["grand_ingested"] == 6
        assert result["grand_failed"] == 0
        assert result["total_sheets_processed"] == 1
        assert result["sheets"][0]["status"] == "success"

    @pytest.mark.asyncio
    @patch("controller.kpiTrackerController.GoogleSheetService")
    async def test_sheet_skipped_on_error(self, MockService):
        """Sheet dengan error di-skip, tidak raise exception jika skip_on_error=True."""
        broken_sheet = {**MOCK_SHEET_ENTRY, "df": None,
                        "meta": None, "error": "Sheet kosong."}
        mock_service = MockService.return_value
        mock_service.fetch_all_sheets_as_dataframes.return_value = [
            broken_sheet]

        db = make_db()
        controller = kpiTrackerController(db)

        result = await controller.ingest_all_sheets_from_google_sheets(
            sheet_url=SHEET_URL,
            nama_orang_override=None,
            skip_on_error=True,
        )

        assert result["total_sheets_processed"] == 1
        assert result["sheets"][0]["status"] == "skipped"
        assert result["sheets"][0]["reason"] == "Sheet kosong."
        assert result["grand_ingested"] == 0

    @pytest.mark.asyncio
    @patch("controller.kpiTrackerController.GoogleSheetService")
    async def test_nama_orang_override_dipakai(self, MockService):
        """nama_orang_override menggantikan nilai dari meta sheet."""
        mock_service = MockService.return_value
        mock_service.fetch_all_sheets_as_dataframes.return_value = [
            MOCK_SHEET_ENTRY]

        db = make_db()
        controller = kpiTrackerController(db)

        captured = {}

        async def fake_bulk_insert(records):
            return 6

        async def fake_create_log(**kwargs):
            captured["nama_orang"] = kwargs["nama_orang"]
            return MOCK_LOG

        with (
            patch.object(controller, "_parse_records",
                         return_value=(MOCK_RECORDS, MOCK_ERRORS)),
            patch.object(controller.repo, "bulk_insert_kpi_records",
                         side_effect=fake_bulk_insert),
            patch.object(controller.repo, "create_ingestion_log",
                         side_effect=fake_create_log),
        ):
            await controller.ingest_all_sheets_from_google_sheets(
                sheet_url=SHEET_URL,
                nama_orang_override="OVERRIDE NAME",
                skip_on_error=True,
            )

        assert captured["nama_orang"] == "OVERRIDE NAME"

    @pytest.mark.asyncio
    @patch("controller.kpiTrackerController.GoogleSheetService")
    async def test_partial_status_ketika_ada_error_rows(self, MockService):
        """Jika ada baris gagal (errors) tapi ada yang berhasil → status partial."""
        mock_service = MockService.return_value
        mock_service.fetch_all_sheets_as_dataframes.return_value = [
            MOCK_SHEET_ENTRY]

        db = make_db()
        controller = kpiTrackerController(db)

        with (
            patch.object(controller, "_parse_records",
                         return_value=(MOCK_RECORDS, ["row 3 invalid"])),
            patch.object(controller.repo, "bulk_insert_kpi_records",
                         new_callable=AsyncMock, return_value=5),
            patch.object(controller.repo, "create_ingestion_log",
                         new_callable=AsyncMock, return_value=MOCK_LOG),
        ):
            result = await controller.ingest_all_sheets_from_google_sheets(
                sheet_url=SHEET_URL,
                nama_orang_override=None,
                skip_on_error=True,
            )

        assert result["sheets"][0]["status"] == "partial"
        assert result["grand_failed"] == 1

    @pytest.mark.asyncio
    @patch("controller.kpiTrackerController.GoogleSheetService")
    async def test_multi_sheet_grand_total(self, MockService):
        """Grand total aggregasi dari beberapa sheet."""
        second_sheet = {
            **MOCK_SHEET_ENTRY,
            "sheet_name": "Februari",
            "sheet_id": 222,
        }
        mock_service = MockService.return_value
        mock_service.fetch_all_sheets_as_dataframes.return_value = [
            MOCK_SHEET_ENTRY, second_sheet]

        db = make_db()
        controller = kpiTrackerController(db)

        with (
            patch.object(controller, "_parse_records",
                         return_value=(MOCK_RECORDS, MOCK_ERRORS)),
            patch.object(controller.repo, "bulk_insert_kpi_records",
                         new_callable=AsyncMock, return_value=6),
            patch.object(controller.repo, "create_ingestion_log",
                         new_callable=AsyncMock, return_value=MOCK_LOG),
        ):
            result = await controller.ingest_all_sheets_from_google_sheets(
                sheet_url=SHEET_URL,
                nama_orang_override=None,
                skip_on_error=True,
            )

        assert result["total_sheets_processed"] == 2
        assert result["grand_ingested"] == 12  # 6 + 6
        assert result["grand_total_rows"] == 12


# ---------------------------------------------------------------------------
# 2. kpiTrackerController — _resolve_status
# ---------------------------------------------------------------------------

class TestResolveStatus:

    def test_success(self):
        assert kpiTrackerController._resolve_status(10, []) == "success"

    def test_partial(self):
        assert kpiTrackerController._resolve_status(5, ["err"]) == "partial"

    def test_failed(self):
        assert kpiTrackerController._resolve_status(0, ["err"]) == "failed"


# ---------------------------------------------------------------------------
# 3. kpiTrackerController — list_sheet_tabs & preview_sheet
# ---------------------------------------------------------------------------

class TestListTabsAndPreview:

    @pytest.mark.asyncio
    @patch("controller.kpiTrackerController.GoogleSheetService")
    async def test_list_sheet_tabs(self, MockService):
        mock_service = MockService.return_value
        mock_service.list_sheets.return_value = [
            {"index": 0, "title": "Januari", "id": 111},
            {"index": 1, "title": "Februari", "id": 222},
        ]

        controller = kpiTrackerController()
        result = await controller.list_sheet_tabs(SHEET_URL)

        assert result == {"tabs": [
            {"index": 0, "title": "Januari", "id": 111},
            {"index": 1, "title": "Februari", "id": 222},
        ]}
        mock_service.list_sheets.assert_called_once_with(SHEET_URL)

    @pytest.mark.asyncio
    @patch("controller.kpiTrackerController.GoogleSheetService")
    async def test_preview_sheet_returns_expected_keys(self, MockService):
        import pandas as pd

        df = pd.DataFrame([{"Nama KPI": "X", "Realisasi": 100}])
        mock_service = MockService.return_value
        mock_service.fetch_sheet_as_dataframe.return_value = (
            df, "FAKE_ID", "Januari", MOCK_META
        )

        controller = kpiTrackerController()
        result = await controller.preview_sheet(
            sheet_url=SHEET_URL,
            sheet_name="Januari",
            sheet_index=0,
        )

        assert "spreadsheet_id" in result
        assert "sheet_name" in result
        assert "extracted_meta" in result
        assert "columns" in result
        assert "total_data_rows" in result
        assert "preview" in result
        assert result["total_data_rows"] == 1


# ---------------------------------------------------------------------------
# 4. GoogleSheetService — unit
# ---------------------------------------------------------------------------

class TestGoogleSheetService:

    def test_extract_spreadsheet_id_valid(self):
        from service.googleSheetService import GoogleSheetService
        svc = GoogleSheetService()
        sid = svc._extract_spreadsheet_id(
            "https://docs.google.com/spreadsheets/d/ABC123xyz/edit#gid=0"
        )
        assert sid == "ABC123xyz"

    def test_extract_spreadsheet_id_invalid(self):
        from fastapi import HTTPException
        from service.googleSheetService import GoogleSheetService
        svc = GoogleSheetService()
        with pytest.raises(HTTPException) as exc_info:
            svc._extract_spreadsheet_id("https://google.com/not-a-sheet")
        assert exc_info.value.status_code == 422

    def test_find_header_row_found(self):
        from service.googleSheetService import GoogleSheetService
        rows = [
            ["KPI TRACKER – PIRMADI S | JANUARI 2025"],
            ["Catatan: ini diabaikan"],
            ["No", "Tanggal", "Nama KPI", "Jenis KPI", "Realisasi", "Keterangan"],
            ["1",  "01-01",   "KPI A",    "Kuantitatif", "100",      "ok"],
        ]
        idx = GoogleSheetService._find_header_row(rows)
        assert idx == 2

    def test_find_header_row_not_found(self):
        from fastapi import HTTPException
        from service.googleSheetService import GoogleSheetService
        rows = [["foo", "bar"], ["baz", "qux"]]
        with pytest.raises(HTTPException) as exc_info:
            GoogleSheetService._find_header_row(rows)
        assert exc_info.value.status_code == 422

    def test_extract_meta_from_title(self):
        from service.googleSheetService import GoogleSheetService
        rows = [
            ["KPI TRACKER – BUDI SANTOSO | MARET 2024"],
            ["No", "Nama KPI", "Jenis KPI", "Realisasi"],
        ]
        meta = GoogleSheetService._extract_meta_from_title(rows, header_row=1)
        assert meta["nama_orang"] == "BUDI SANTOSO"
        assert meta["bulan"] == "Maret"
        assert meta["bulan_num"] == 3
        assert meta["tahun"] == 2024

    def test_extract_meta_no_title(self):
        from service.googleSheetService import GoogleSheetService
        rows = [["No", "Nama KPI", "Jenis KPI", "Realisasi"]]
        meta = GoogleSheetService._extract_meta_from_title(rows, header_row=0)
        assert meta["nama_orang"] is None
        assert meta["bulan"] is None

    def test_clean_headers_dedup(self):
        from service.googleSheetService import GoogleSheetService
        raw = ["No", "Nama KPI", "Nama KPI", "", "Status"]
        cleaned = GoogleSheetService._clean_headers(raw)
        assert cleaned[1] == "Nama KPI"
        assert cleaned[2] == "Nama KPI_2"
        assert cleaned[3].startswith("_empty_")
        assert cleaned[4] == "Status"

    def test_build_dataframe_drops_empty_cols_and_rows(self):
        from service.googleSheetService import GoogleSheetService
        import pandas as pd
        all_values = [
            ["KPI TRACKER – X | JANUARI 2025"],
            ["No", "Nama KPI", ""],
            ["1", "A", ""],
            ["", "", ""],  # baris kosong — harus di-drop
        ]
        svc = GoogleSheetService()
        df = svc._build_dataframe(all_values, header_row_idx=1)
        assert "_empty_2" not in df.columns
        assert len(df) == 1  # baris kosong sudah di-drop


# ---------------------------------------------------------------------------
# 5. Schema — validasi Pydantic
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
                SheetIngestionResult(sheet_name="Februari",
                                     status="skipped", reason="Sheet kosong."),
            ],
        )
        assert resp.overall_status == "success"
        assert resp.sheets[1].reason == "Sheet kosong."

    def test_sheet_ingestion_result_optional_fields(self):
        """Semua field opsional kecuali sheet_name dan status."""
        r = SheetIngestionResult(sheet_name="Maret", status="skipped")
        assert r.log_id is None
        assert r.meta is None
        assert r.errors is None

    def test_sheet_meta_all_optional(self):
        m = SheetMeta(nama_orang=None, bulan=None, bulan_num=None, tahun=None)
        assert m.tahun is None


@pytest.mark.asyncio
async def test_create_ingestion_log_with_source_type():
    """create_ingestion_log deve aceitar e salvar source_type."""
    from unittest.mock import AsyncMock, MagicMock, patch
    from sqlalchemy.ext.asyncio import AsyncSession
    from repository.kpiTrackerRepository import kpiTrackerRepository

    db = AsyncMock(spec=AsyncSession)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    with patch.object(db, "add") as mock_add:
        repo = kpiTrackerRepository(db)
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
