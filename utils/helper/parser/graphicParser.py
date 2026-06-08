from __future__ import annotations

import re
from dataclasses import dataclass
import pandas as pd
from typing import cast

from utils.constants.graphicConstants import (
    HEADER_WORDS,
    TRL_EXACT_RE,
    EXPR_RE,
    SCALE_MAP,
    TRL_PATTERN,
    COLOR_THRESHOLD_RE,
    NOTES_HINTS,
)


@dataclass
class ParsedValue:
    """Hasil parse satu cell ekspresi KPI."""

    numeric: float | None  # nilai numerik yang diekstrak
    original: str  # string asli
    operator: str = ""  # "≥", "≤", ">", "<", "" (none)
    unit: str = ""  # "%" | "hari" | "M/org" | "juta" | "ribu" | ""
    is_header: bool = False  # True jika cell adalah baris header dummy ("Target")
    scale: float = 1.0  # faktor pengali (M → 1_000_000, dst.)

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
    Parser untuk kolom target / realisasi dengan format campuran.
    """

    _HEADER_WORDS = HEADER_WORDS
    _TRL_RE = TRL_EXACT_RE
    _EXPR_RE = EXPR_RE
    _SCALE_MAP = SCALE_MAP

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
            op = op.replace(">=", "≥").replace("<=", "≤")

            num_str = num_raw.replace(",", ".")
            try:
                num = float(num_str)
            except ValueError:
                return ParsedValue(numeric=None, original=original)

            unit = (unit_raw or "").strip()
            scale = 1.0

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

        return ParsedValue(numeric=None, original=original)

    def parse_series(self, series: pd.Series) -> list[ParsedValue]:
        return [self.parse(v) for v in series]

    def to_numeric_series(
        self, series: pd.Series, use_scaled: bool = False
    ) -> pd.Series:
        parsed = self.parse_series(series)
        values = []
        for p in parsed:
            if use_scaled:
                values.append(p.scaled_numeric)
            else:
                values.append(p.numeric)
        return pd.Series(values, index=series.index, dtype=float)

    def is_kpi_value_column(self, series: pd.Series, threshold: float = 0.5) -> bool:
        non_null = series.dropna()
        if len(non_null) == 0:
            return False
        parsed = self.parse_series(non_null)
        parseable = sum(1 for p in parsed if not p.is_header and p.numeric is not None)
        return (parseable / len(parsed)) >= threshold

    def dominant_unit(self, series: pd.Series) -> str:
        parsed = self.parse_series(series.dropna())
        units = [p.unit for p in parsed if p.unit and not p.is_header]
        if not units:
            return ""
        return max(set(units), key=units.count)


_KPI_PARSER = KpiValueParser()


def parse_trl_value(series: pd.Series) -> pd.Series | None:
    str_series = series.astype(str)
    matches = str_series.str.extract(TRL_PATTERN, expand=False)
    if matches.notna().sum() == 0:
        return None
    return pd.to_numeric(matches, errors="coerce")


def is_trl_column(series: pd.Series) -> bool:
    return parse_trl_value(series) is not None


def is_color_threshold_column(series: pd.Series) -> bool:
    non_null = series.dropna().astype(str)
    if len(non_null) == 0:
        return False
    matched = non_null.apply(lambda v: bool(COLOR_THRESHOLD_RE.match(v.strip())))
    return matched.mean() >= 0.8


def is_notes_column(col_name: str, series: pd.Series) -> bool:
    if any(h in col_name.lower() for h in NOTES_HINTS):
        return True
    str_lengths = series.dropna().astype(str).str.len()
    return bool(str_lengths.mean() > 40) if len(str_lengths) > 0 else False
