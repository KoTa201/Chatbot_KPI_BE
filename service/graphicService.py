"""
graphicSeervice.py
Generate visualisasi grafik dari hasil SQL untuk pipeline SRAG.
Tipe grafik yang didukung: bar, pie, donut, line, grouped_bar, stacked_bar, progress, trl_progress.

Changelog:
- Tambah KpiValueParser: parse ekspresi campuran (≥22%, ≤90 hari, 1.2 M/org, TRL 3, dst.)
- Simpan metadata parse (operator, satuan, original) untuk anotasi chart
- Kolom target/realisasi kini di-parse sebelum divisualisasikan
- Anotasi bar chart tampilkan nilai asli (bukan angka mentah)
- _is_threshold_column diperbarui agar tidak salah buang kolom target/realisasi
"""

from __future__ import annotations

import base64
import io
import re
import uuid as _uuid_module
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast
from uuid import UUID

import pandas as pd
from fastapi import HTTPException, status


# ===========================================================================
# KpiValueParser — parse ekspresi KPI menjadi nilai numerik + metadata
# ===========================================================================

@dataclass
class ParsedValue:
    """Hasil parse satu cell ekspresi KPI."""
    numeric: float | None          # nilai numerik yang diekstrak
    original: str                  # string asli
    operator: str = ""             # "≥", "≤", ">", "<", "" (none)
    unit: str = ""                 # "%" | "hari" | "M/org" | "juta" | "ribu" | ""
    is_header: bool = False        # True jika cell adalah baris header dummy ("Target")
    scale: float = 1.0             # faktor pengali (M → 1_000_000, dst.)

    @property
    def display(self) -> str:
        """Label singkat untuk ditampilkan di chart."""
        if self.is_header or self.numeric is None:
            return self.original
        op = self.operator
        if self.unit == "TRL":
            return f"TRL {self.numeric:.4g}"
        if self.unit == "%":
            return f"{op}{self.numeric:.4g}%"
        if self.unit:
            return f"{op}{self.numeric:.4g} {self.unit}"
        return f"{op}{self.numeric:.4g}"

    @property
    def scaled_numeric(self) -> float | None:
        """Nilai setelah dikali faktor skala (misal M → jutaan)."""
        if self.numeric is None:
            return None
        return self.numeric * self.scale


class KpiValueParser:
    """
    Parser untuk kolom target / realisasi dengan format campuran:

    Format yang didukung (semua case-insensitive, spasi opsional):
      ≥22%        →  op="≥"  num=22    unit="%"
      ≤10%        →  op="≤"  num=10    unit="%"
      ≥1.2 M/org  →  op="≥"  num=1.2   unit="M/org"  scale=1_000_000
      ≤90 hari    →  op="≤"  num=90    unit="hari"
      100%        →  op=""   num=100   unit="%"
      ≥8          →  op="≥"  num=8     unit=""
      12          →  op=""   num=12    unit=""
      TRL 3       →  op=""   num=3     unit="TRL"
      Target      →  is_header=True
      (kosong/nan)→  numeric=None
    """

    # Kata-kata yang dianggap header / placeholder bukan nilai
    _HEADER_WORDS = frozenset({
        "target", "realisasi", "pencapaian", "actual", "nilai",
        "kpi", "indikator", "satuan", "-", "n/a", "na", "",
    })

    # Operator Unicode + ASCII
    _OP_PATTERN = r"([≥≤><]|>=|<=)?"

    # Angka desimal (termasuk koma sebagai pemisah desimal)
    _NUM_PATTERN = r"(\d[\d.,]*)"

    # Satuan opsional setelah angka
    _UNIT_PATTERN = r"\s*([a-zA-Z%/][^\s]*(?:\s+[a-zA-Z/][^\s]*)*)?"

    # TRL prefix
    _TRL_RE = re.compile(r"(?i)^\s*trl\s*(\d+)\s*$")

    # Full expression pattern
    _EXPR_RE = re.compile(
        r"^\s*" + _OP_PATTERN + r"\s*" + _NUM_PATTERN + _UNIT_PATTERN + r"\s*$",
        re.UNICODE,
    )

    # Skala untuk satuan
    _SCALE_MAP: dict[str, float] = {
        "m":       1_000_000,   # M/org, M (juta)
        "jt":      1_000_000,
        "juta":    1_000_000,
        "k":       1_000,       # ribu
        "rb":      1_000,
        "ribu":    1_000,
        "miliar":  1_000_000_000,
        "b":       1_000_000_000,
    }

    def parse(self, raw: object) -> ParsedValue:
        """Parse satu nilai menjadi ParsedValue."""
        if raw is None or (isinstance(raw, float) and pd.isna(raw)):
            return ParsedValue(numeric=None, original="")

        original = str(raw).strip()

        # Kosong
        if not original:
            return ParsedValue(numeric=None, original=original)

        # Header dummy
        if original.lower() in self._HEADER_WORDS:
            return ParsedValue(numeric=None, original=original, is_header=True)

        # TRL
        trl_match = self._TRL_RE.match(original)
        if trl_match:
            return ParsedValue(
                numeric=float(trl_match.group(1)),
                original=original,
                unit="TRL",
            )

        # Coba pure numeric dulu (paling cepat)
        cleaned = original.replace(",", ".")
        try:
            return ParsedValue(numeric=float(cleaned), original=original)
        except ValueError:
            pass

        # Full expression parse
        m = self._EXPR_RE.match(original)
        if m:
            op_raw, num_raw, unit_raw = m.group(1), m.group(2), m.group(3)

            op = op_raw or ""
            # Normalise ">=" / "<="
            op = op.replace(">=", "≥").replace("<=", "≤")

            num_str = num_raw.replace(",", ".")
            try:
                num = float(num_str)
            except ValueError:
                return ParsedValue(numeric=None, original=original)

            unit = (unit_raw or "").strip()
            scale = 1.0

            # Deteksi satuan skala (misal "M/org" → scale dari "M")
            unit_lower = unit.lower()
            for key, factor in self._SCALE_MAP.items():
                if unit_lower.startswith(key):
                    scale = factor
                    break

            return ParsedValue(
                numeric=num,
                original=original,
                operator=op,
                unit=unit,
                scale=scale,
            )

        # Gagal parse
        return ParsedValue(numeric=None, original=original)

    def parse_series(self, series: pd.Series) -> list[ParsedValue]:
        return [self.parse(v) for v in series]

    def to_numeric_series(self, series: pd.Series, use_scaled: bool = False) -> pd.Series:
        """
        Konversi satu kolom ke Series float.
        use_scaled=True → kalikan dengan faktor skala satuan.
        """
        parsed = self.parse_series(series)
        values = []
        for p in parsed:
            if use_scaled:
                values.append(p.scaled_numeric)
            else:
                values.append(p.numeric)
        return pd.Series(values, index=series.index, dtype=float)

    def is_kpi_value_column(self, series: pd.Series, threshold: float = 0.5) -> bool:
        """
        Kembalikan True jika ≥ threshold baris berhasil di-parse sebagai
        ekspresi KPI (bukan header dummy dan bukan pure string narasi).
        """
        non_null = series.dropna()
        if len(non_null) == 0:
            return False
        parsed = self.parse_series(non_null)
        parseable = sum(
            1 for p in parsed
            if not p.is_header and p.numeric is not None
        )
        return (parseable / len(parsed)) >= threshold

    def dominant_unit(self, series: pd.Series) -> str:
        """Kembalikan satuan paling dominan di kolom (untuk label sumbu)."""
        parsed = self.parse_series(series.dropna())
        units = [p.unit for p in parsed if p.unit and not p.is_header]
        if not units:
            return ""
        return max(set(units), key=units.count)


# Singleton global agar tidak perlu instansiasi berulang
_KPI_PARSER = KpiValueParser()


# ===========================================================================
# Helper-helper lama (dipertahankan & disesuaikan)
# ===========================================================================

_TRL_PATTERN = re.compile(r"(?i)trl\s*(\d+)")


def _parse_trl_value(series: pd.Series) -> pd.Series | None:
    str_series = series.astype(str)
    matches = str_series.str.extract(_TRL_PATTERN, expand=False)
    if matches.notna().sum() == 0:
        return None
    return pd.to_numeric(matches, errors="coerce")


def _is_trl_column(series: pd.Series) -> bool:
    return _parse_trl_value(series) is not None


# Threshold COLOR kolom ("≥100%", "67–99%", "<67%") — BUKAN kolom nilai KPI
# Pola ini spesifik: range seperti "67–99%" atau hanya operator+angka TANPA satuan lain
_COLOR_THRESHOLD_RE = re.compile(r"^\d+[–—\-]\d+%$|^[<≥≤>]=?\d+%$")


def _is_color_threshold_column(series: pd.Series) -> bool:
    """
    True jika kolom berisi nilai-nilai warna/status threshold seperti:
    '≥100%', '67–99%', '<67%' — yaitu rentang atau batas tunggal TANPA konteks lain.
    Berbeda dari kolom target realisasi yang bisa berisi '≥22%'.
    Heuristik: semua baris non-null cocok dengan pola range atau operator+persen saja,
    DAN tidak ada angka murni atau satuan teks.
    """
    non_null = series.dropna().astype(str)
    if len(non_null) == 0:
        return False
    matched = non_null.apply(lambda v: bool(_COLOR_THRESHOLD_RE.match(v.strip())))
    # Harus semua (atau hampir semua) baris cocok pola ini
    return matched.mean() >= 0.8


_NOTES_HINTS = ("note", "notes", "keterangan", "catatan", "deskripsi", "description")


def _is_notes_column(col_name: str, series: pd.Series) -> bool:
    if any(h in col_name.lower() for h in _NOTES_HINTS):
        return True
    str_lengths = series.dropna().astype(str).str.len()
    return bool(str_lengths.mean() > 40) if len(str_lengths) > 0 else False


# ===========================================================================
# Dataclass hasil
# ===========================================================================

@dataclass
class GraphicResult:
    chart_type: str
    image_url: str
    kpi_name: str = ""
    image_base64: str = field(default="")


# ===========================================================================
# Service utama
# ===========================================================================

class GraphicSeervice:
    """Service untuk membuat grafik dari data hasil query SQL."""

    SUPPORTED_CHART_TYPES = {
        "bar", "pie", "donut", "line",
        "grouped_bar", "stacked_bar",
        "progress",      # actual vs target per KPI / bulan
        "trl_progress",  # TRL timeline
    }

    def __init__(self, public_dir: str | Path = "public"):
        self.public_dir = Path(public_dir)
        self.parser = _KPI_PARSER

        self.value_column_hints = (
            "total", "jumlah", "sum", "avg", "average", "rata", "nilai",
            "score", "persen", "percentage", "realisasi", "count", "qty",
            "value", "actual", "pencapaian",
        )
        self.target_column_hints = ("target", "goal", "sasaran")
        self.category_column_hints = (
            "bulan", "month", "tanggal", "date", "periode", "nama", "kpi",
            "divisi", "kategori", "category", "label",
        )
        self.month_column_hints = ("bulan", "bulan_num", "month", "month_num")
        self.month_labels = {
            1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "Mei", 6: "Jun",
            7: "Jul", 8: "Agu", 9: "Sep", 10: "Okt", 11: "Nov", 12: "Des",
        }

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    def generateGraphic(
        self,
        query_result: list[dict],
        chart_type: str = "bar",
        session_id: UUID | None = None,
    ) -> GraphicResult:
        if not query_result:
            raise ValueError("Data kosong, grafik tidak dapat dibuat.")

        chart_type = (chart_type or "bar").strip().lower()
        if chart_type not in self.SUPPORTED_CHART_TYPES:
            chart_type = "bar"

        raw_df = pd.DataFrame(query_result)
        if raw_df.empty:
            raise ValueError("Data kosong, grafik tidak dapat dibuat.")

        # 1. Buang kolom warna/threshold dan narasi panjang
        df = self._drop_non_data_columns(raw_df)

        # 2. Parse kolom KPI-value (target/realisasi) → numerik, simpan metadata
        df, kpi_meta = self._parse_kpi_columns(df)

        # 3. Auto-detect chart type
        if chart_type == "bar":
            chart_type = self._auto_detect_chart_type(df) or "bar"

        plt = self._load_matplotlib_pyplot()
        image_bytes = self._render_chart(df=df, chart_type=chart_type, plt=plt, kpi_meta=kpi_meta)

        image_url = self._save_chart_image(image_bytes=image_bytes, session_id=session_id)
        image_base64 = base64.b64encode(image_bytes).decode("utf-8")
        return GraphicResult(chart_type=chart_type, image_url=image_url, image_base64=image_base64)

    def generateGraphicPerKpi(
        self,
        query_result: list[dict],
        chart_type: str = "bar",
        session_id: UUID | None = None,
    ) -> list[GraphicResult]:
        """
        Buat SATU grafik per nilai unik kolom KPI yang terdeteksi.
        Jika tidak ada kolom KPI, fallback ke generateGraphic (list 1 elemen).
        Return: list[GraphicResult] diurutkan sesuai urutan kemunculan KPI di data.
        """
        if not query_result:
            raise ValueError("Data kosong, grafik tidak dapat dibuat.")

        chart_type = (chart_type or "bar").strip().lower()
        if chart_type not in self.SUPPORTED_CHART_TYPES:
            chart_type = "bar"

        raw_df = pd.DataFrame(query_result)
        if raw_df.empty:
            raise ValueError("Data kosong, grafik tidak dapat dibuat.")

        df = self._drop_non_data_columns(raw_df)
        df, kpi_meta = self._parse_kpi_columns(df)

        if chart_type == "bar":
            chart_type = self._auto_detect_chart_type(df) or "bar"

        kpi_col = self._pick_kpi_column(df)
        if kpi_col is None or df[kpi_col].nunique() <= 1:
            single = self.generateGraphic(query_result, chart_type, session_id)
            return [single]

        # Urutan KPI sesuai kemunculan pertama di data
        kpi_order = list(dict.fromkeys(df[kpi_col].dropna().astype(str).tolist()))
        plt = self._load_matplotlib_pyplot()
        results: list[GraphicResult] = []

        for kpi_name in kpi_order:
            mask   = df[kpi_col].astype(str) == kpi_name
            subset = df[mask].copy()
            if subset.empty:
                continue

            subset_meta = self._slice_meta(kpi_meta, list(subset.index))

            # Always re-detect per subset so TRL KPIs get trl_progress
            # and integer KPIs get the right chart type independently
            sub_chart_type = self._auto_detect_chart_type(subset) or chart_type or "bar"

            try:
                image_bytes = self._render_chart(
                    df=subset.reset_index(drop=True),
                    chart_type=sub_chart_type,
                    plt=plt,
                    kpi_meta=subset_meta,
                    title_prefix=kpi_name,
                )
                image_url = self._save_chart_image(image_bytes, session_id)
                image_base64 = base64.b64encode(image_bytes).decode("utf-8")
                results.append(GraphicResult(
                    chart_type=sub_chart_type,
                    image_url=image_url,
                    kpi_name=kpi_name,
                    image_base64=image_base64,
                ))
            except Exception as exc:
                # Satu KPI gagal tidak menghentikan seluruh proses
                import warnings
                warnings.warn(f"Gagal render KPI '{kpi_name}': {exc}")
                continue

        if not results:
            single = self.generateGraphic(query_result, chart_type, session_id)
            return [single]

        return results

    # ------------------------------------------------------------------
    # Helper: slice kpi_meta untuk subset baris (by original integer index)
    # ------------------------------------------------------------------
    def _slice_meta(
        self,
        kpi_meta: dict[str, list[ParsedValue]],
        orig_indices: list[int],
    ) -> dict[str, list[ParsedValue]]:
        """
        Kembalikan kpi_meta hanya untuk baris dengan indeks asli `orig_indices`.
        Setelah reset_index(drop=True) pada subset, urutan list sudah benar (0-based).
        """
        result: dict[str, list[ParsedValue]] = {}
        for col, pv_list in kpi_meta.items():
            result[col] = [pv_list[i] for i in orig_indices if i < len(pv_list)]
        return result

    # ------------------------------------------------------------------
    # Pre-processing 1: buang kolom warna / narasi
    # ------------------------------------------------------------------
    def _drop_non_data_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        drop_cols: list[str] = []
        for col in df.columns:
            series = df[col]
            if _is_color_threshold_column(series):
                drop_cols.append(col)
            elif _is_notes_column(col, series):
                drop_cols.append(col)
        return df.drop(columns=drop_cols) if drop_cols else df

    # ------------------------------------------------------------------
    # Pre-processing 2: parse kolom KPI-value → float, simpan metadata
    # ------------------------------------------------------------------
    def _parse_kpi_columns(
        self, df: pd.DataFrame
    ) -> tuple[pd.DataFrame, dict[str, list[ParsedValue]]]:
        """
        Untuk setiap kolom yang terdeteksi sebagai kolom nilai KPI
        (target / realisasi / ekspresi campuran), replace dengan nilai
        numerik dan simpan ParsedValue list untuk anotasi.

        Return (df_with_numeric_cols, {col_name: [ParsedValue, ...]})
        """
        df = df.copy()
        meta: dict[str, list[ParsedValue]] = {}

        for col in df.columns:
            series = df[col]
            # Skip jika kolom sudah sepenuhnya numerik
            if pd.to_numeric(series, errors="coerce").notna().mean() >= 0.9:
                continue
            # Cek apakah ini kolom KPI-value
            if self.parser.is_kpi_value_column(series, threshold=0.4):
                parsed_list = self.parser.parse_series(series)
                meta[col] = parsed_list
                # Gunakan scaled_numeric supaya satuan skala (M, K) sudah diterapkan
                df[col] = pd.Series(
                    [p.scaled_numeric for p in parsed_list],
                    index=series.index,
                    dtype=float,
                )
        return df, meta

    # ------------------------------------------------------------------
    # Auto-detect chart type
    # ------------------------------------------------------------------
    def _auto_detect_chart_type(self, df: pd.DataFrame) -> str | None:
        cols_lower = [c.lower() for c in df.columns]

        for col in df.columns:
            if _is_trl_column(df[col]):
                return "trl_progress"

        has_actual = any(h in c for c in cols_lower for h in ("actual", "realisasi", "pencapaian"))
        has_target = any(h in c for c in cols_lower for h in self.target_column_hints)
        if has_actual and has_target:
            return "progress"

        has_kpi  = any("kpi" in c or "nama" in c or "kategori" in c for c in cols_lower)
        has_time = any(h in c for c in cols_lower for h in self.month_column_hints)
        if has_kpi and has_time:
            return "grouped_bar"

        return None

    # ------------------------------------------------------------------
    # Dispatch render
    # ------------------------------------------------------------------
    def _render_chart(
        self,
        df: pd.DataFrame,
        chart_type: str,
        plt,
        kpi_meta: dict[str, list[ParsedValue]],
        title_prefix: str = "",
    ) -> bytes:
        if chart_type == "trl_progress":
            return self._render_trl_progress(df=df, plt=plt, title_prefix=title_prefix)
        if chart_type == "progress":
            return self._render_progress(df=df, plt=plt, kpi_meta=kpi_meta)
        if chart_type in ("grouped_bar", "stacked_bar"):
            return self._render_multi_series(df=df, chart_type=chart_type, plt=plt, title_prefix=title_prefix)
        if chart_type == "line":
            return self._render_line(df=df, plt=plt, title_prefix=title_prefix)
        return self._render_simple(df=df, chart_type=chart_type, plt=plt, kpi_meta=kpi_meta, title_prefix=title_prefix)

    # ------------------------------------------------------------------
    # Render: TRL Progress
    # ------------------------------------------------------------------
    def _render_trl_progress(self, df: pd.DataFrame, plt, title_prefix: str = "") -> bytes:
        trl_col, trl_numeric = self._find_trl_column(df)
        if trl_col is None:
            raise ValueError("Kolom TRL tidak ditemukan.")

        df = df.copy()
        df["__trl_num__"] = trl_numeric

        time_col = self._pick_time_column(df, exclude=[trl_col])
        kpi_col  = self._pick_kpi_column(df, exclude=[c for c in [trl_col, time_col] if c])

        fig, ax = plt.subplots(figsize=(10, 5))

        if kpi_col and time_col:
            for kpi_name, group in df.groupby(kpi_col):
                grp = group.sort_values(time_col)
                xs  = self._month_labels_for(grp[time_col])
                ax.plot(xs, grp["__trl_num__"], marker="o", label=str(kpi_name))
                ax.fill_between(xs, grp["__trl_num__"], alpha=0.08)
            ax.legend(title=kpi_col, bbox_to_anchor=(1.01, 1), loc="upper left", fontsize=8)
        elif time_col:
            grp = df.sort_values(time_col)
            ax.plot(self._month_labels_for(grp[time_col]), grp["__trl_num__"], marker="o", color="#2563EB")
        else:
            ax.bar(range(len(df)), df["__trl_num__"], color="#2563EB")

        ax.set_yticks(range(1, 10))
        ax.set_ylabel("TRL Level")
        ax.set_xlabel(time_col or "")
        ax.set_title(f"{title_prefix} — TRL Progress per Bulan" if title_prefix else "TRL Progress per Bulan")
        ax.grid(axis="y", alpha=0.3)
        ax.tick_params(axis="x", rotation=30)

        fig.tight_layout()
        return self._fig_to_bytes(fig=fig, plt=plt)

    # ------------------------------------------------------------------
    # Render: Progress — actual vs target
    # ------------------------------------------------------------------
    def _render_progress(
        self,
        df: pd.DataFrame,
        plt,
        kpi_meta: dict[str, list[ParsedValue]],
    ) -> bytes:
        actual_col = self._find_column_by_hints(df, ("actual", "realisasi", "pencapaian"))
        target_col = self._find_column_by_hints(df, self.target_column_hints)
        exclude    = [c for c in [actual_col, target_col] if c]
        kpi_col    = self._pick_kpi_column(df, exclude=exclude)
        time_col   = self._pick_time_column(df, exclude=exclude + [kpi_col] if kpi_col else exclude)

        df = df.copy()

        # Pastikan kolom numerik (mungkin sudah di-parse di _parse_kpi_columns)
        for col in [actual_col, target_col]:
            if col:
                if _is_trl_column(df[col]):
                    df[col] = _parse_trl_value(df[col])
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

        # Bangun label sumbu Y
        if kpi_col and time_col:
            df["__label__"] = df[kpi_col].astype(str) + " (Bln " + df[time_col].astype(str) + ")"
        elif kpi_col:
            df["__label__"] = df[kpi_col].astype(str)
        elif time_col:
            df["__label__"] = self._month_labels_for(df[time_col])
        else:
            df["__label__"] = [f"Baris {i+1}" for i in range(len(df))]

        df = df.tail(15)

        # Satuan untuk label sumbu X
        x_unit = ""
        if actual_col and actual_col in kpi_meta:
            x_unit = self.parser.dominant_unit(
                pd.Series([p.original for p in kpi_meta[actual_col]])
            )
        xlabel = f"Nilai ({x_unit})" if x_unit and x_unit != "%" else "Nilai"

        fig, ax = plt.subplots(figsize=(10, max(4, len(df) * 0.5)))
        y_pos = list(range(len(df)))

        if target_col and actual_col:
            ax.barh(y_pos, df[target_col], color="#CBD5E1", label="Target", height=0.55)
            ax.barh(y_pos, df[actual_col], color="#2563EB", label="Actual", height=0.35)

            for i, (a, t) in enumerate(zip(df[actual_col], df[target_col])):
                pct   = (a / t * 100) if t else 0
                color = "#16A34A" if pct >= 100 else ("#D97706" if pct >= 67 else "#DC2626")
                # Tampilkan label dari metadata asli jika ada
                actual_label = ""
                target_label = ""
                if actual_col in kpi_meta and i < len(kpi_meta[actual_col]):
                    actual_label = kpi_meta[actual_col][i].display
                if target_col in kpi_meta and i < len(kpi_meta[target_col]):
                    target_label = kpi_meta[target_col][i].display

                annotation = f"{pct:.0f}%"
                if actual_label:
                    annotation = f"{actual_label}  ({pct:.0f}%)"

                ax.text(
                    max(t, a) * 1.02 + 0.01,
                    i,
                    annotation,
                    va="center",
                    fontsize=7.5,
                    color=color,
                )

            ax.legend(loc="lower right", fontsize=8)
        elif actual_col:
            ax.barh(y_pos, df[actual_col], color="#2563EB")
        else:
            raise ValueError("Tidak ada kolom actual/realisasi untuk progress chart.")

        ax.set_yticks(y_pos)
        ax.set_yticklabels(df["__label__"].tolist(), fontsize=8)
        ax.set_xlabel(xlabel)
        ax.set_title("KPI Progress: Actual vs Target")
        ax.grid(axis="x", alpha=0.3)

        fig.tight_layout()
        return self._fig_to_bytes(fig=fig, plt=plt)

    # ------------------------------------------------------------------
    # Render: Grouped / Stacked Bar
    # ------------------------------------------------------------------
    def _render_multi_series(self, df: pd.DataFrame, chart_type: str, plt, title_prefix: str = "") -> bytes:
        value_col = self._find_column_by_hints(df, self.value_column_hints) or self._pick_best_numeric(df)
        if not value_col:
            raise ValueError("Tidak ada kolom numerik ditemukan.")

        time_col = self._pick_time_column(df, exclude=[value_col])
        kpi_col  = self._pick_kpi_column(df, exclude=[c for c in [value_col, time_col] if c])

        df = df.copy()
        df[value_col] = pd.to_numeric(df[value_col], errors="coerce").fillna(0)

        if time_col and kpi_col:
            pivot = df.pivot_table(index=time_col, columns=kpi_col, values=value_col, aggfunc="sum")
            pivot.index = self._month_labels_for(pd.Series(pivot.index))
        elif kpi_col:
            pivot = df.set_index(kpi_col)[[value_col]]
        else:
            pivot = df[[value_col]]

        pivot = pivot.fillna(0).tail(12)

        fig, ax = plt.subplots(figsize=(11, 5))
        pivot.plot(kind="bar", stacked=(chart_type == "stacked_bar"), ax=ax, colormap="tab10")

        ax.set_title(f"{title_prefix} ({chart_type})" if title_prefix else f"Visualisasi KPI ({chart_type})")
        ax.set_xlabel(time_col or "")
        ax.set_ylabel(value_col)
        ax.tick_params(axis="x", rotation=30)
        ax.legend(bbox_to_anchor=(1.01, 1), loc="upper left", fontsize=8)
        ax.grid(axis="y", alpha=0.3)

        fig.tight_layout()
        return self._fig_to_bytes(fig=fig, plt=plt)

    # ------------------------------------------------------------------
    # Render: Line
    # ------------------------------------------------------------------
    def _render_line(self, df: pd.DataFrame, plt, title_prefix: str = "") -> bytes:
        value_col = self._find_column_by_hints(df, self.value_column_hints) or self._pick_best_numeric(df)
        if not value_col:
            raise ValueError("Tidak ada kolom numerik ditemukan.")

        time_col = self._pick_time_column(df, exclude=[value_col])
        kpi_col  = self._pick_kpi_column(df, exclude=[c for c in [value_col, time_col] if c])

        df = df.copy()
        df[value_col] = pd.to_numeric(df[value_col], errors="coerce").fillna(0)

        fig, ax = plt.subplots(figsize=(10, 5))

        if kpi_col and time_col:
            for label, grp in df.groupby(kpi_col):
                grp = grp.sort_values(time_col)
                ax.plot(self._month_labels_for(grp[time_col]), grp[value_col], marker="o", label=str(label))
            ax.legend(title=kpi_col, bbox_to_anchor=(1.01, 1), loc="upper left", fontsize=8)
        elif time_col:
            df = df.sort_values(time_col)
            ax.plot(self._month_labels_for(df[time_col]), df[value_col], marker="o", color="#2563EB")
        else:
            ax.plot(df[value_col].tolist(), marker="o", color="#2563EB")

        ax.set_title(f"{title_prefix} — Tren" if title_prefix else "Tren KPI (Line Chart)")
        ax.set_xlabel(time_col or "")
        ax.set_ylabel(value_col)
        ax.tick_params(axis="x", rotation=30)
        ax.grid(alpha=0.3)

        fig.tight_layout()
        return self._fig_to_bytes(fig=fig, plt=plt)

    # ------------------------------------------------------------------
    # Render: Simple bar / pie / donut
    # ------------------------------------------------------------------
    def _render_simple(
        self,
        df: pd.DataFrame,
        chart_type: str,
        plt,
        kpi_meta: dict[str, list[ParsedValue]],
        title_prefix: str = "",
    ) -> bytes:
        category_col, value_col, chart_df = self._prepare_chart_data(df, chart_type)

        fig, ax = plt.subplots(figsize=(9, 5))

        if chart_type == "bar":
            bars = ax.bar(chart_df[category_col], chart_df[value_col], color="#2563EB")
            ax.set_xlabel(category_col)
            # Label sumbu Y dengan satuan jika diketahui
            unit_label = ""
            if value_col in kpi_meta:
                unit_label = self.parser.dominant_unit(
                    pd.Series([p.original for p in kpi_meta[value_col]])
                )
            ax.set_ylabel(f"{value_col} ({unit_label})" if unit_label else value_col)
            ax.tick_params(axis="x", rotation=30)
            # Anotasi di atas bar dengan label asli
            if value_col in kpi_meta:
                meta_list = kpi_meta[value_col]
                for rect, cat in zip(bars, chart_df[category_col]):
                    idx_matches = chart_df.index[chart_df[category_col] == cat].tolist()
                    if idx_matches and idx_matches[0] < len(meta_list):
                        pv = meta_list[idx_matches[0]]
                        if pv.display:
                            ax.text(
                                rect.get_x() + rect.get_width() / 2,
                                rect.get_height() * 1.01,
                                pv.display,
                                ha="center", va="bottom", fontsize=7,
                            )
        else:
            wedges, *_ = ax.pie(
                chart_df[value_col],
                labels=chart_df[category_col].tolist(),
                autopct="%1.1f%%",
                startangle=90,
            )
            ax.axis("equal")
            if chart_type == "donut":
                ax.add_artist(plt.Circle((0, 0), 0.55, fc="white"))
            for wedge in wedges:
                wedge.set_linewidth(1)
                wedge.set_edgecolor("white")

        ax.set_title(f"{title_prefix} ({chart_type})" if title_prefix else f"Visualisasi KPI ({chart_type})")
        fig.tight_layout()
        return self._fig_to_bytes(fig=fig, plt=plt)

    # ------------------------------------------------------------------
    # _prepare_chart_data (dipakai _render_simple)
    # ------------------------------------------------------------------
    def _prepare_chart_data(
        self, dataframe: pd.DataFrame, chart_type: str
    ) -> tuple[str, str, pd.DataFrame]:
        data = dataframe.copy()

        # TRL → numerik
        for col in data.columns:
            if _is_trl_column(data[col]):
                data[col] = _parse_trl_value(data[col])

        numeric_valid_counts: dict[str, int] = {}
        for col in data.columns:
            n = int(cast(pd.Series, pd.to_numeric(data[col], errors="coerce")).notna().sum())
            if n > 0:
                numeric_valid_counts[col] = n

        best_numeric = self._pick_value_column(numeric_valid_counts)
        if not best_numeric:
            raise ValueError("Tidak ada kolom numerik untuk divisualisasikan.")

        data[best_numeric] = pd.to_numeric(data[best_numeric], errors="coerce")
        data = data.dropna(subset=[best_numeric])
        if data.empty:
            raise ValueError("Nilai numerik tidak valid untuk pembuatan grafik.")

        category_col = self._pick_category_column(data, best_numeric, numeric_valid_counts)
        if not category_col:
            category_col = "__baris__"
            data[category_col] = [f"Baris {i+1}" for i in range(len(data))]

        chart_df = data[[category_col, best_numeric]].copy()

        if self._is_month_like_column(category_col):
            mn = cast(pd.Series, pd.to_numeric(chart_df[category_col], errors="coerce"))
            if mn.notna().all() and mn.between(1, 12).all():
                chart_df["__o__"] = mn.astype(int)
                chart_df = chart_df.sort_values("__o__").drop(columns=["__o__"])
                chart_df[category_col] = mn.astype(int).map(self.month_labels).fillna(chart_df[category_col]).astype(str)
            else:
                chart_df[category_col] = chart_df[category_col].astype(str)
        else:
            chart_df[category_col] = chart_df[category_col].astype(str)
            if chart_type in {"pie", "donut"}:
                chart_df = chart_df.sort_values(by=best_numeric, ascending=False)

        return category_col, best_numeric, chart_df.head(12)

    def _pick_value_column(self, numeric_valid_counts: dict[str, int]) -> str | None:
        if not numeric_valid_counts:
            return None

        def score(col: str) -> tuple[int, int]:
            norm = col.lower()
            h = sum(1 for hint in self.value_column_hints if hint in norm)
            if self._is_month_like_column(col):
                h -= 2
            return h, numeric_valid_counts[col]

        return max(numeric_valid_counts, key=score)

    def _pick_category_column(
        self, data: pd.DataFrame, value_column: str, numeric_valid_counts: dict[str, int]
    ) -> str | None:
        candidates = [c for c in data.columns if c != value_column]
        if not candidates:
            return None

        month_cands = [c for c in candidates if self._is_month_like_column(c)]
        if month_cands:
            return month_cands[0]

        hint_cands = [c for c in candidates if any(h in c.lower() for h in self.category_column_hints)]
        if hint_cands:
            return hint_cands[0]

        non_numeric = [c for c in candidates if c not in numeric_valid_counts]
        if non_numeric:
            return non_numeric[0]

        return candidates[0]

    # ------------------------------------------------------------------
    # Utilities: column pickers
    # ------------------------------------------------------------------
    def _find_trl_column(self, df: pd.DataFrame) -> tuple[str | None, pd.Series | None]:
        for col in df.columns:
            parsed = _parse_trl_value(df[col])
            if parsed is not None:
                return col, parsed
        return None, None

    def _find_column_by_hints(self, df: pd.DataFrame, hints: tuple | list) -> str | None:
        for col in df.columns:
            if any(h in col.lower() for h in hints):
                return col
        return None

    def _pick_time_column(self, df: pd.DataFrame, exclude: list[str | None] = []) -> str | None:
        excl = [c for c in exclude if c]
        for col in df.columns:
            if col not in excl and self._is_month_like_column(col):
                return col
        return None

    def _pick_kpi_column(self, df: pd.DataFrame, exclude: list[str | None] = []) -> str | None:
        excl = [c for c in exclude if c]
        kpi_hints = ("kpi", "nama", "kategori", "category", "produk", "product", "name", "indikator")
        for col in df.columns:
            if col not in excl and any(h in col.lower() for h in kpi_hints):
                return col
        for col in df.columns:
            if col not in excl:
                if pd.to_numeric(df[col], errors="coerce").isna().mean() > 0.5:
                    return col
        return None

    def _pick_best_numeric(self, df: pd.DataFrame) -> str | None:
        counts: dict[str, int] = {}
        for col in df.columns:
            n = int(pd.to_numeric(df[col], errors="coerce").notna().sum())
            if n > 0:
                counts[col] = n
        if not counts:
            return None
        return max(counts, key=lambda c: (
            sum(1 for h in self.value_column_hints if h in c.lower()),
            counts[c],
        ))

    def _month_labels_for(self, series: pd.Series) -> list[str]:
        numeric = pd.to_numeric(series, errors="coerce")
        if numeric.notna().all() and numeric.between(1, 12).all():
            return [self.month_labels.get(int(v), str(v)) for v in numeric]
        return series.astype(str).tolist()

    def _is_month_like_column(self, column_name: str) -> bool:
        return any(hint in column_name.lower() for hint in self.month_column_hints)

    # ------------------------------------------------------------------
    # I/O
    # ------------------------------------------------------------------
    def _fig_to_bytes(self, fig, plt) -> bytes:
        buf = io.BytesIO()
        try:
            fig.savefig(buf, format="png", dpi=140, bbox_inches="tight")
            return buf.getvalue()
        finally:
            plt.close(fig)

    def _save_chart_image(self, image_bytes: bytes, session_id: UUID | None) -> str:
        folder = str(session_id) if session_id else "unsessioned"
        fname  = f"{_uuid_module.uuid4()}.png"
        rel    = Path("charts") / folder / fname
        out    = self.public_dir / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(image_bytes)
        return f"/public/{rel.as_posix()}"

    @staticmethod
    def _load_matplotlib_pyplot():
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            return plt
        except ImportError as err:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Matplotlib belum tersedia untuk generate visualisasi.",
            ) from err