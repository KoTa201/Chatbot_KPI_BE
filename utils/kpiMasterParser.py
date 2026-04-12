"""
utils/kpiMasterParser.py
Parse a raw Google Sheets DataFrame containing KPI Master data.

Sheet format:
  - Category header row: only column-0 is filled, text starts with "KPI "
  - Column header row:   first cell is exactly "KPI"
  - Data row:            all other non-blank rows
  - Blank row:           all cells empty/NaN — skipped
"""

from typing import Optional
import pandas as pd

# Maps canonical field names to possible column header aliases (lowercase, stripped)
_COLUMN_ALIASES: dict[str, list[str]] = {
    "kpi_name":              ["kpi", "nama kpi", "kpi name"],
    "definisi_operasional":  ["definisi operasional", "definisi", "definition"],
    "dihitung":              ["dihitung", "counted", "yang dihitung"],
    "tidak_dihitung":        ["tidak dihitung", "not counted", "yang tidak dihitung"],
    "rumus":                 ["rumus", "formula"],
    "target":                ["target"],
    "sumber_data":           ["sumber data", "sumber", "data source"],
    "achieve":               ["achieve", "achievement"],
    "partial":               ["partial"],
    "fail":                  ["fail", "failed"],
    "responsibility_persons": [
        "responsobility persons", "responsibility persons",
        "responsible persons", "person", "persons", "penanggung jawab",
    ],
}


def _resolve(header_cells: list[str], field: str) -> Optional[int]:
    """Return column index for field, or None if not found."""
    aliases = _COLUMN_ALIASES.get(field, [field])
    for i, cell in enumerate(header_cells):
        if str(cell).strip().lower() in aliases:
            return i
    return None


def _is_blank_row(row: pd.Series) -> bool:
    return all(v is None or (isinstance(v, float) and pd.isna(v)) or str(v).strip() == "" for v in row)


def _is_category_row(row: pd.Series) -> bool:
    """Category row: only col-0 is filled and starts with 'KPI '."""
    if _is_blank_row(row):
        return False
    val = str(row.iloc[0]).strip()
    rest_empty = all(
        v is None or (isinstance(v, float) and pd.isna(v)
                      ) or str(v).strip() == ""
        for v in row.iloc[1:]
    )
    return val.lower().startswith("kpi ") and rest_empty


def _is_header_row(row: pd.Series) -> bool:
    """Column header row: first cell is exactly 'KPI' (case-insensitive)."""
    return str(row.iloc[0]).strip().lower() == "kpi"


def _clean_str(val) -> Optional[str]:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).strip()
    return s if s.lower() not in ("nan", "none", "") else None


def _get_field(row: pd.Series, col_map: dict, field: str) -> Optional[str]:
    """Return the cleaned string value for field from row using col_map."""
    idx = col_map.get(field)
    if idx is None:
        return None
    val = row.iloc[idx] if idx < len(row) else None
    return _clean_str(val)


def _normalize_persons(val) -> Optional[str]:
    raw = _clean_str(val)
    if not raw:
        return None
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return ", ".join(parts)


def parse_kpi_master_dataframe(
    df: pd.DataFrame,
    spreadsheet_id: str,
    sheet_name: str,
    tahun: int = 0,
) -> tuple[list[dict], list[str]]:
    """
    Parse a raw KPI Master DataFrame into a list of record dicts.

    Returns:
        (records, errors)
    """
    if df.empty:
        return [], ["Sheet is empty"]

    records: list[dict] = []
    errors: list[str] = []
    current_category: Optional[str] = None
    col_map: dict[str, Optional[int]] = {}

    for row_idx, row in df.iterrows():
        if _is_blank_row(row):
            continue

        if _is_category_row(row):
            current_category = str(row.iloc[0]).strip()
            col_map = {}  # reset column map for this section
            continue

        if _is_header_row(row):
            header_cells = [str(v) for v in row.tolist()]
            col_map = {
                field: _resolve(header_cells, field)
                for field in _COLUMN_ALIASES
            }
            continue

        if current_category is None:
            errors.append(
                f"Row {row_idx + 1}: no category header found before data row, skipped.")
            continue

        if not col_map:
            errors.append(
                f"Row {row_idx + 1}: data row found but no column header row seen yet in category '{current_category}', skipped.")
            continue

        kpi_name = _get_field(row, col_map, "kpi_name")
        if not kpi_name:
            errors.append(f"Row {row_idx + 1}: kpi_name is empty, skipped.")
            continue

        records.append({
            "tahun":                  tahun,
            "category":               current_category,
            "kpi_name":               kpi_name,
            "definisi_operasional":   _get_field(row, col_map, "definisi_operasional"),
            "dihitung":               _get_field(row, col_map, "dihitung"),
            "tidak_dihitung":         _get_field(row, col_map, "tidak_dihitung"),
            "rumus":                  _get_field(row, col_map, "rumus"),
            "target":                 _get_field(row, col_map, "target"),
            "sumber_data":            _get_field(row, col_map, "sumber_data"),
            "achieve":                _get_field(row, col_map, "achieve"),
            "partial":                _get_field(row, col_map, "partial"),
            "fail":                   _get_field(row, col_map, "fail"),
            "responsibility_persons": _normalize_persons(_get_field(row, col_map, "responsibility_persons")),
        })

    return records, errors
