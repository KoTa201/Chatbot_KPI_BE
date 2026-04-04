"""
tests/kpi_master_test.py
Unit tests for KPI Master parser.
Run: pytest tests/kpi_master_test.py -v
"""
import pandas as pd
import pytest
from utils.kpiMasterParser import parse_kpi_master_dataframe


def _make_df(rows: list[list]) -> pd.DataFrame:
    """Build a raw DataFrame (no header) from a list of rows."""
    return pd.DataFrame(rows)


def test_parse_extracts_category_and_records():
    """Parser must detect category header and extract records under it."""
    rows = [
        ["KPI High Level", None, None, None, None, None, None, None, None, None, None],
        ["KPI", "Definisi Operasional", "Dihitung", "Tidak Dihitung", "Rumus", "Target",
         "Sumber Data", "Achieve", "Partial", "Fail", "Responsobility Persons"],
        ["Revenue Achievement", "Total nilai PO signed", "Semua PO", "Forecast",
         "Total PO ÷ Target", "20 M", "Finance", "≥100%", "85–99%", "<85%",
         "Pirmadi S, Djoko K"],
    ]
    df = _make_df(rows)
    records, errors = parse_kpi_master_dataframe(df, "FAKE_ID", "Sheet1", tahun=2024)
    assert len(records) == 1
    assert records[0]["category"] == "KPI High Level"
    assert records[0]["kpi_name"] == "Revenue Achievement"
    assert records[0]["target"] == "20 M"
    assert records[0]["responsibility_persons"] == "Pirmadi S, Djoko K"
    assert errors == []


def test_parse_skips_blank_rows():
    """Blank rows between sections must be skipped."""
    rows = [
        ["KPI High Level", None, None, None, None, None, None, None, None, None, None],
        ["KPI", "Definisi Operasional", "Dihitung", "Tidak Dihitung", "Rumus", "Target",
         "Sumber Data", "Achieve", "Partial", "Fail", "Responsobility Persons"],
        ["Revenue Achievement", "Desc", "A", "B", "C", "20 M", "Finance", "≥100%", "85–99%", "<85%", "Pirmadi S"],
        [None, None, None, None, None, None, None, None, None, None, None],  # blank row
        ["KPI Product Management", None, None, None, None, None, None, None, None, None, None],
        ["KPI", "Definisi Operasional", "Dihitung", "Tidak Dihitung", "Rumus", "Target",
         "Sumber Data", "Achieve", "Partial", "Fail", "Responsobility Persons"],
        ["Product Launch", "Desc", "A", "B", "C", "3", "Product doc", "≥100%", "67–99%", "<67%", "Erlan H"],
    ]
    df = _make_df(rows)
    records, errors = parse_kpi_master_dataframe(df, "FAKE_ID", "Sheet1", tahun=2024)
    assert len(records) == 2
    assert records[0]["category"] == "KPI High Level"
    assert records[1]["category"] == "KPI Product Management"


def test_parse_empty_sheet_returns_empty():
    """Empty sheet returns empty records and a warning error."""
    df = _make_df([])
    records, errors = parse_kpi_master_dataframe(df, "FAKE_ID", "Sheet1", tahun=2024)
    assert records == []
    assert len(errors) == 1
    assert "empty" in errors[0].lower()


def test_parse_normalizes_responsibility_persons():
    """Responsibility persons are trimmed and comma-separated cleanly."""
    rows = [
        ["KPI High Level", None, None, None, None, None, None, None, None, None, None],
        ["KPI", "Definisi Operasional", "Dihitung", "Tidak Dihitung", "Rumus", "Target",
         "Sumber Data", "Achieve", "Partial", "Fail", "Responsobility Persons"],
        ["Revenue Achievement", "Desc", "A", "B", "C", "20 M", "Finance", "≥100%",
         "85–99%", "<85%", "  Pirmadi S ,  Djoko K  "],
    ]
    df = _make_df(rows)
    records, _ = parse_kpi_master_dataframe(df, "FAKE_ID", "Sheet1", tahun=2024)
    assert records[0]["responsibility_persons"] == "Pirmadi S, Djoko K"


def test_parse_data_row_before_category_header_goes_to_errors():
    """Data rows encountered before any category header must produce an error."""
    rows = [
        ["Revenue Achievement", "Desc", "A", "B", "C", "20 M", "Finance", "≥100%", "85–99%", "<85%", "Pirmadi S"],
    ]
    df = _make_df(rows)
    records, errors = parse_kpi_master_dataframe(df, "FAKE_ID", "Sheet1", tahun=2024)
    assert records == []
    assert len(errors) == 1


def test_parse_skips_row_with_empty_kpi_name():
    """Rows with empty kpi_name field must be skipped and produce an error."""
    rows = [
        ["KPI High Level", None, None, None, None, None, None, None, None, None, None],
        ["KPI", "Definisi Operasional", "Dihitung", "Tidak Dihitung", "Rumus", "Target",
         "Sumber Data", "Achieve", "Partial", "Fail", "Responsobility Persons"],
        [None, "Some desc", "A", "B", "C", "20 M", "Finance", "≥100%", "85–99%", "<85%", "Pirmadi S"],  # empty kpi_name
    ]
    df = _make_df(rows)
    records, errors = parse_kpi_master_dataframe(df, "FAKE_ID", "Sheet1", tahun=2024)
    assert records == []
    assert len(errors) == 1


def test_parse_stamps_source_sheet_metadata():
    """source_sheet_id and source_sheet_name must be present on every record."""
    rows = [
        ["KPI High Level", None, None, None, None, None, None, None, None, None, None],
        ["KPI", "Definisi Operasional", "Dihitung", "Tidak Dihitung", "Rumus", "Target",
         "Sumber Data", "Achieve", "Partial", "Fail", "Responsobility Persons"],
        ["Revenue Achievement", "Desc", "A", "B", "C", "20 M", "Finance", "≥100%", "85–99%", "<85%", "Pirmadi S"],
    ]
    df = _make_df(rows)
    records, _ = parse_kpi_master_dataframe(df, "MY_SHEET_ID", "MySheet", tahun=2024)
    assert records[0]["source_sheet_id"] == "MY_SHEET_ID"
    assert records[0]["source_sheet_name"] == "MySheet"


def test_parse_stamps_tahun_on_records():
    """tahun must be present on every record with the value passed in."""
    rows = [
        ["KPI High Level", None, None, None, None, None, None, None, None, None, None],
        ["KPI", "Definisi Operasional", "Dihitung", "Tidak Dihitung", "Rumus", "Target",
         "Sumber Data", "Achieve", "Partial", "Fail", "Responsobility Persons"],
        ["Revenue Achievement", "Desc", "A", "B", "C", "20 M", "Finance", "≥100%", "85–99%", "<85%", "Pirmadi S"],
    ]
    df = _make_df(rows)
    records, _ = parse_kpi_master_dataframe(df, "FAKE_ID", "Sheet1", tahun=2024)
    assert records[0]["tahun"] == 2024


@pytest.mark.asyncio
async def test_kpi_master_repository_upsert_by_tahun():
    """upsert_by_tahun must execute an upsert statement and return the record count."""
    from unittest.mock import AsyncMock
    from sqlalchemy.ext.asyncio import AsyncSession
    from repository.kpiMasterRepository import KPIMasterRepository

    db = AsyncMock(spec=AsyncSession)
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()

    records = [
        {
            "tahun": 2024,
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
            "source_sheet_id": "FAKE",
            "source_sheet_name": "Sheet1",
        }
    ]

    repo = KPIMasterRepository(db)
    count = await repo.upsert_by_tahun(records)
    assert count == 1
    db.execute.assert_called_once()  # upsert statement was issued
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_kpi_master_controller_ingest_calls_upsert_and_log():
    """Controller must call upsert_by_tahun with tahun in records and create_ingestion_log."""
    from unittest.mock import AsyncMock, MagicMock, patch
    from sqlalchemy.ext.asyncio import AsyncSession
    from controller.kpiMasterController import KPIMasterController

    db = AsyncMock(spec=AsyncSession)
    controller = KPIMasterController(db)

    mock_records = [{"tahun": 2024, "category": "KPI High Level", "kpi_name": "Revenue Achievement",
                     "definisi_operasional": None, "dihitung": None, "tidak_dihitung": None,
                     "rumus": None, "target": "20 M", "sumber_data": None, "achieve": "≥100%",
                     "partial": "85–99%", "fail": "<85%", "responsibility_persons": "Pirmadi S",
                     "source_sheet_id": "FAKE_ID", "source_sheet_name": "Sheet1"}]
    mock_errors: list = []
    mock_log = MagicMock()
    mock_log.id = 1

    with (
        patch.object(controller, "_fetch_sheet", return_value=(MagicMock(), "FAKE_ID", "Sheet1")),
        patch("controller.kpiMasterController.parse_kpi_master_dataframe",
              return_value=(mock_records, mock_errors)),
        patch.object(controller.kpi_repo, "upsert_by_tahun", new_callable=AsyncMock, return_value=1),
        patch.object(controller.log_repo, "create_ingestion_log", new_callable=AsyncMock, return_value=mock_log),
    ):
        result = await controller.ingest_kpi_master("https://docs.google.com/spreadsheets/d/FAKE_ID", tahun=2024)
        controller.kpi_repo.upsert_by_tahun.assert_called_once_with(mock_records)
        controller.log_repo.create_ingestion_log.assert_called_once()
        call_kwargs = controller.log_repo.create_ingestion_log.call_args.kwargs
        assert call_kwargs["source_type"] == "kpi_master"
        assert result["status"] == "success"
        assert result["tahun"] == 2024
