"""
services/parser.py
Parsing & normalisasi DataFrame KPI Tracker -> list of dict siap simpan ke PostgreSQL.
"""

import re
from typing import Optional

import pandas as pd

COLUMN_ALIASES = {
    "nama_kpi":   ["nama kpi", "name kpi", "kpi name", "nama_kpi", "kpi"],
    "tanggal":    ["tanggal", "date", "tgl", "bulan", "month"],
    "realisasi":  ["realisasi", "realization", "actual", "pencapaian", "achievement"],
    "keterangan": ["keterangan", "notes", "note", "catatan", "description", "remarks", "comment"],
}


def resolve_column(df_columns: list, field: str) -> Optional[str]:
    aliases = COLUMN_ALIASES.get(field, [field])
    for col in df_columns:
        if col.strip().lower() in aliases:
            return col
    return None


def extract_year(value, fallback: Optional[int] = None) -> Optional[int]:
    """
    Ekstrak tahun dari string tanggal.
    Jika tidak ditemukan, gunakan fallback (tahun dari judul sheet).
    """
    if value is not None and not (isinstance(value, float) and pd.isna(value)):
        match = re.search(r"\b(20\d{2}|19\d{2})\b", str(value))
        if match:
            return int(match.group(1))
    return fallback


def normalize_realisasi(val) -> Optional[str]:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    cleaned = str(val).strip()
    return cleaned if cleaned.lower() not in ("", "nan", "none") else None





def parse_dataframe(
    df: pd.DataFrame,
    nama_orang: str,
    spreadsheet_id: str,
    sheet_name: str,
    tahun_override: Optional[int] = None,   # <- dari judul sheet
) -> tuple:
    """
    Parse DataFrame menjadi list of dict siap disimpan ke PostgreSQL.

    Args:
        df             : DataFrame hasil fetch dari Google Sheets
        nama_orang     : Nama pemilik KPI (sudah diekstrak dari judul)
        spreadsheet_id : ID spreadsheet sumber
        sheet_name     : Nama tab/sheet sumber
        tahun_override : Tahun dari judul sheet, dipakai jika kolom tanggal kosong

    Returns:
        (records: list[dict], errors: list[str])
    """
    records = []
    errors = []

    df.columns = [str(c).strip() for c in df.columns]
    cols = df.columns.tolist()

    col_nama_kpi = resolve_column(cols, "nama_kpi")
    col_tanggal = resolve_column(cols, "tanggal")
    col_realisasi = resolve_column(cols, "realisasi")
    col_ket = resolve_column(cols, "keterangan")

    if not col_nama_kpi:
        raise ValueError(
            f"Kolom 'Nama KPI' tidak ditemukan. Kolom tersedia: {cols}"
        )

    for idx, row in df.iterrows():
        try:
            nama_kpi = str(row[col_nama_kpi]).strip(
            ) if pd.notna(row[col_nama_kpi]) else ""
            if not nama_kpi or nama_kpi.lower() in ("nan", "none", ""):
                errors.append(f"Baris {idx + 2}: 'Nama KPI' kosong, dilewati.")
                continue

            # Tahun: dari kolom tanggal, fallback ke tahun judul sheet
            raw_tanggal = row[col_tanggal] if col_tanggal else None
            tahun = extract_year(raw_tanggal, fallback=tahun_override)

            realisasi = normalize_realisasi(
                row[col_realisasi]) if col_realisasi else None
            keterangan = (
                str(row[col_ket]).strip()
                if col_ket and pd.notna(row[col_ket])
                else None
            )
            if keterangan and keterangan.lower() in ("nan", "none", ""):
                keterangan = None

            raw = {
                "nama_kpi":   nama_kpi,
                "tahun":      tahun,
                "realisasi":  realisasi,
                "nama_orang": nama_orang,
                "keterangan": keterangan,
            }

            records.append({
                **raw,
                "source_sheet_id":   spreadsheet_id,
                "source_sheet_name": sheet_name,
            })

        except Exception as e:
            errors.append(f"Baris {idx + 2}: {str(e)}")

    return records, errors
