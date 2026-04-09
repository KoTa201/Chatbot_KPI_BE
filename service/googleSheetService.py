"""
services/google_sheets.py
Akses Google Sheets via Service Account (tanpa OAuth user).

Struktur sheet yang didukung:
    Baris 1 : KPI TRACKER – PIRMADI S  |  JANUARI 2025   (judul)
    Baris 2 : Catatan: ...                                (opsional, dilewati)
    Baris 3 : No | Bulan | Tanggal | Jenis KPI | Nama KPI | ... (header kolom)
    Baris 4+: data
"""

import re
from typing import Optional

import gspread
import pandas as pd
from fastapi import HTTPException
from google.oauth2.service_account import Credentials

from config import settings

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

BULAN_ID = {
    "januari": 1,  "februari": 2, "maret": 3,    "april": 4,
    "mei": 5,      "juni": 6,     "juli": 7,      "agustus": 8,
    "september": 9, "oktober": 10, "november": 11, "desember": 12,
}

HEADER_KEYWORDS = [
    "nama kpi", "jenis kpi", "nama aktivitas", "realisasi",
    "keterangan", "satuan target", "tanggal", "deskripsi",
]


class GoogleSheetService:
    def __init__(self):
        self._client: Optional[gspread.Client] = None
        self.google_credentials_path: str = settings.GOOGLE_CREDENTIALS_PATH

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def fetch_sheet_as_dataframe(
        self,
        sheet_url: str,
        sheet_name: Optional[str] = None,
        sheet_index: int = 0,
        header=True,
    ) -> tuple:
        """
        Ambil data dari satu sheet sebagai DataFrame + metadata.

        Args:
            header: If None, return all rows as raw DataFrame with integer columns
                    (no header detection). Useful for KPI Master sheets.

        Returns:
            (DataFrame, spreadsheet_id, sheet_name_aktif, meta: dict)
        """
        client = self._get_client()
        spreadsheet_id = self._extract_spreadsheet_id(sheet_url)
        spreadsheet = self._open_spreadsheet(client, spreadsheet_id)
        worksheet = self._select_worksheet(
            spreadsheet, sheet_name, sheet_index)

        if header is None:
            return self._process_worksheet_raw(worksheet, spreadsheet_id)
        return self._process_worksheet(worksheet, spreadsheet_id)

    def fetch_all_sheets_as_dataframes(
        self,
        sheet_url: str,
        skip_on_error: bool = True,
    ) -> list[dict]:
        """
        Ingest SEMUA sheet/tab dalam satu spreadsheet sekaligus.

        Args:
            sheet_url   : URL Google Sheets.
            skip_on_error: Jika True, sheet yang gagal di-parse dilewati
                           dan dicatat di field 'error'. Jika False,
                           exception langsung dilempar.

        Returns:
            List of dict, satu item per sheet:
            [
                {
                    "sheet_index"   : int,
                    "sheet_name"    : str,
                    "sheet_id"      : int,
                    "spreadsheet_id": str,
                    "df"            : pd.DataFrame,  # None jika error
                    "meta"          : dict,           # None jika error
                    "error"         : str | None,
                },
                ...
            ]
        """
        client = self._get_client()
        spreadsheet_id = self._extract_spreadsheet_id(sheet_url)
        spreadsheet = self._open_spreadsheet(client, spreadsheet_id)
        worksheets = spreadsheet.worksheets()

        results = []
        for i, worksheet in enumerate(worksheets):
            entry = {
                "sheet_index": i,
                "sheet_name": worksheet.title,
                "sheet_id": worksheet.id,
                "spreadsheet_id": spreadsheet_id,
                "df": None,
                "meta": None,
                "error": None,
            }

            try:
                df, _, _, meta = self._process_worksheet(
                    worksheet, spreadsheet_id)
                entry["df"] = df
                entry["meta"] = meta
            except HTTPException as e:
                if not skip_on_error:
                    raise
                entry["error"] = e.detail
            except Exception as e:
                if not skip_on_error:
                    raise
                entry["error"] = str(e)

            results.append(entry)

        if not results:
            raise HTTPException(
                status_code=422, detail="Spreadsheet tidak memiliki sheet.")

        return results

    def list_sheets(self, sheet_url: str) -> list:
        """Daftar semua sheet/tab dalam satu spreadsheet."""
        client = self._get_client()
        spreadsheet_id = self._extract_spreadsheet_id(sheet_url)

        try:
            spreadsheet = client.open_by_key(spreadsheet_id)
            return [
                {"index": i, "title": ws.title, "id": ws.id}
                for i, ws in enumerate(spreadsheet.worksheets())
            ]
        except gspread.exceptions.SpreadsheetNotFound:
            raise HTTPException(
                status_code=404,
                detail="Spreadsheet tidak ditemukan atau belum diberi akses ke service account.",
            )

    # ------------------------------------------------------------------ #
    #  Core worksheet processor (dipakai oleh fetch_sheet & fetch_all)    #
    # ------------------------------------------------------------------ #

    def _process_worksheet(
        self,
        worksheet: gspread.Worksheet,
        spreadsheet_id: str,
    ) -> tuple:
        """
        Proses satu worksheet menjadi (DataFrame, spreadsheet_id, sheet_name, meta).
        Dipisah dari fetch_sheet_as_dataframe agar bisa di-reuse fetch_all.
        """
        all_values = worksheet.get_all_values()
        if not all_values:
            raise HTTPException(
                status_code=422,
                detail=f"Sheet '{worksheet.title}' kosong.",
            )

        header_row_idx = self._find_header_row(all_values)
        meta = self._extract_meta_from_title(
            all_values, header_row=header_row_idx)
        meta["header_row"] = header_row_idx

        df = self._build_dataframe(all_values, header_row_idx)

        return df, spreadsheet_id, worksheet.title, meta

    def _process_worksheet_raw(
        self,
        worksheet: gspread.Worksheet,
        spreadsheet_id: str,
    ) -> tuple:
        """Return all rows as a raw DataFrame with integer column indices."""
        all_values = worksheet.get_all_values()
        if not all_values:
            raise HTTPException(
                status_code=422,
                detail=f"Sheet '{worksheet.title}' kosong.",
            )
        df = pd.DataFrame(all_values)
        df = df.replace("", None)
        return df, spreadsheet_id, worksheet.title, {}

    # ------------------------------------------------------------------ #
    #  Auth                                                                #
    # ------------------------------------------------------------------ #

    def _get_client(self) -> gspread.Client:
        if self._client is None:
            self._client = self._build_client()
        return self._client

    def _build_client(self) -> gspread.Client:
        try:
            creds = Credentials.from_service_account_file(
                self.google_credentials_path,
                scopes=SCOPES,
            )
            return gspread.authorize(creds)
        except FileNotFoundError:
            raise HTTPException(
                status_code=500,
                detail=(
                    f"File credentials tidak ditemukan: '{self.google_credentials_path}'. "
                    "Pastikan file JSON Service Account sudah ada dan path-nya benar di .env"
                ),
            )
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Gagal autentikasi Google Service Account: {str(e)}",
            )

    # ------------------------------------------------------------------ #
    #  Spreadsheet & worksheet access                                      #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _extract_spreadsheet_id(url: str) -> str:
        match = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", url)
        if not match:
            raise HTTPException(
                status_code=422,
                detail="URL tidak valid. Gunakan URL Google Sheets yang benar.",
            )
        return match.group(1)

    @staticmethod
    def _open_spreadsheet(
        client: gspread.Client,
        spreadsheet_id: str,
    ) -> gspread.Spreadsheet:
        try:
            return client.open_by_key(spreadsheet_id)
        except gspread.exceptions.SpreadsheetNotFound:
            raise HTTPException(
                status_code=404,
                detail=(
                    "Spreadsheet tidak ditemukan atau service account belum diberi akses. "
                    "Share spreadsheet ke email service account sebagai Viewer."
                ),
            )
        except gspread.exceptions.APIError as e:
            raise HTTPException(
                status_code=502,
                detail=f"Google Sheets API error: {str(e)}",
            )

    @staticmethod
    def _select_worksheet(
        spreadsheet: gspread.Spreadsheet,
        sheet_name: Optional[str],
        sheet_index: int,
    ) -> gspread.Worksheet:
        try:
            if sheet_name:
                return spreadsheet.worksheet(sheet_name)
            return spreadsheet.get_worksheet(sheet_index)
        except gspread.exceptions.WorksheetNotFound:
            available = [ws.title for ws in spreadsheet.worksheets()]
            raise HTTPException(
                status_code=404,
                detail=f"Sheet '{sheet_name}' tidak ditemukan. Sheet tersedia: {available}",
            )

    # ------------------------------------------------------------------ #
    #  Header detection                                                    #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _find_header_row(all_values: list[list[str]]) -> int:
        best_row = None
        best_score = 0

        for i, row in enumerate(all_values):
            row_text = " ".join(str(c).strip().lower() for c in row if c)
            score = sum(1 for kw in HEADER_KEYWORDS if kw in row_text)
            if score > best_score:
                best_score = score
                best_row = i

        if best_row is None or best_score < 2:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Baris header kolom tabel tidak ditemukan. "
                    f"Pastikan sheet memiliki kolom seperti: {HEADER_KEYWORDS}"
                ),
            )

        return best_row

    # ------------------------------------------------------------------ #
    #  Metadata extraction                                                 #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _extract_meta_from_title(
        all_values: list[list[str]],
        header_row: int,
    ) -> dict:
        meta = {
            "nama_orang": None,
            "bulan":      None,
            "bulan_num":  None,
            "tahun":      None,
        }

        for row in all_values[:header_row]:
            row_text = " ".join(str(c).strip() for c in row if c)

            if "KPI TRACKER" not in row_text.upper():
                continue

            name_match = re.search(
                r"KPI\s+TRACKER\s*[–\-]\s*(.+?)\s*\|",
                row_text,
                re.IGNORECASE,
            )
            if name_match:
                meta["nama_orang"] = name_match.group(1).strip()

            period_match = re.search(
                r"\|\s*([A-Za-z]+)\s+(\d{4})",
                row_text,
                re.IGNORECASE,
            )
            if period_match:
                bulan_str = period_match.group(1).strip()
                meta["bulan"] = bulan_str.capitalize()
                meta["bulan_num"] = BULAN_ID.get(bulan_str.lower())
                meta["tahun"] = int(period_match.group(2))

            break

        return meta

    # ------------------------------------------------------------------ #
    #  DataFrame builder                                                   #
    # ------------------------------------------------------------------ #

    def _build_dataframe(
        self,
        all_values: list[list[str]],
        header_row_idx: int,
    ) -> pd.DataFrame:
        if header_row_idx >= len(all_values) - 1:
            raise HTTPException(
                status_code=422,
                detail="Sheet hanya memiliki header tanpa baris data.",
            )

        raw_headers = all_values[header_row_idx]
        headers = self._clean_headers(raw_headers)
        data_rows = all_values[header_row_idx + 1:]

        df = pd.DataFrame(data_rows, columns=headers)

        cols_to_drop = [c for c in df.columns if c.startswith("_empty_")]
        df = df.drop(columns=cols_to_drop, errors="ignore")
        df = df.replace("", None)
        df = df.dropna(how="all").reset_index(drop=True)

        return df

    @staticmethod
    def _clean_headers(raw_headers: list) -> list:
        seen = {}
        cleaned = []

        for i, h in enumerate(raw_headers):
            h = str(h).strip()
            if not h:
                cleaned.append(f"_empty_{i}")
                continue
            if h not in seen:
                seen[h] = 1
                cleaned.append(h)
            else:
                seen[h] += 1
                cleaned.append(f"{h}_{seen[h]}")

        return cleaned
