from __future__ import annotations

from typing import cast
import pandas as pd

from utils.helper.parser.graphicParser import (
    ParsedValue,
    KpiValueParser,
    is_trl_column,
    parse_trl_value,
    is_color_threshold_column,
    is_notes_column,
)
from utils.constants.graphicConstants import (
    VALUE_COLUMN_HINTS,
    TARGET_COLUMN_HINTS,
    CATEGORY_COLUMN_HINTS,
    MONTH_COLUMN_HINTS,
)


class GraphicDataPreparer:
    """Mengurus pembersihan DataFrame, seleksi kolom, dan penyiapan data visualisasi."""

    def __init__(
        self,
        parser: KpiValueParser,
        value_column_hints=VALUE_COLUMN_HINTS,
        target_column_hints=TARGET_COLUMN_HINTS,
        category_column_hints=CATEGORY_COLUMN_HINTS,
        month_column_hints=MONTH_COLUMN_HINTS,
        month_labels=None,
    ):
        self.parser: KpiValueParser = parser
        self.value_column_hints: list[str] = value_column_hints
        self.target_column_hints: list[str] = target_column_hints
        self.category_column_hints: list[str] = category_column_hints
        self.month_column_hints: list[str] = month_column_hints
        self.month_labels: list[str] | None = month_labels

    def drop_non_data_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        drop_cols: list[str] = []
        for col in df.columns:
            series = df[col]
            if is_color_threshold_column(series) or is_notes_column(col, series):
                drop_cols.append(col)
        return df.drop(columns=drop_cols) if drop_cols else df

    def parse_kpi_columns(
        self, df: pd.DataFrame
    ) -> tuple[pd.DataFrame, dict[str, list[ParsedValue]]]:
        df = df.copy()
        meta: dict[str, list[ParsedValue]] = {}

        for col in df.columns:
            series = df[col]
            if pd.to_numeric(series, errors="coerce").notna().mean() >= 0.9:
                continue
            if self.parser.is_kpi_value_column(series, threshold=0.4):
                parsed_list = self.parser.parse_series(series)
                meta[col] = parsed_list
                df[col] = pd.Series(
                    [p.scaled_numeric for p in parsed_list],
                    index=series.index,
                    dtype=float,
                )
        return df, meta

    def prepare_chart_data(
        self, dataframe: pd.DataFrame, chart_type: str
    ) -> tuple[str, str, pd.DataFrame]:
        data = dataframe.copy()

        for col in data.columns:
            if is_trl_column(data[col]):
                data[col] = parse_trl_value(data[col])

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

        category_col = self._pick_category_column(
            data, best_numeric, numeric_valid_counts
        )
        if not category_col:
            category_col = "__baris__"
            data[category_col] = [f"Baris {i + 1}" for i in range(len(data))]

        chart_df = data[[category_col, best_numeric]].copy()
        chart_df[category_col] = chart_df[category_col].astype(str)

        # Check if it is a KPI status/achievement category column
        cat_lower = chart_df[category_col].str.lower().str.strip().tolist()
        status_keywords = {"achieve", "achieved", "partial", "fail", "failed", "gagal", "tercapai", "belum tercapai"}
        if any(any(kw in val for kw in status_keywords) for val in cat_lower):
            expected_statuses = ["Achieve", "Partial", "Fail"]
            existing_mapped = []
            for val in chart_df[category_col]:
                val_clean = val.strip().lower()
                if "achieve" in val_clean:
                    existing_mapped.append("Achieve")
                elif "partial" in val_clean:
                    existing_mapped.append("Partial")
                elif "fail" in val_clean or "gagal" in val_clean or "belum" in val_clean:
                    existing_mapped.append("Fail")
                else:
                    existing_mapped.append(val)
            chart_df[category_col] = existing_mapped

            # Add missing statuses with 0.0 value
            for estatus in expected_statuses:
                if estatus not in chart_df[category_col].values:
                    new_row = pd.DataFrame([{category_col: estatus, best_numeric: 0.0}])
                    chart_df = pd.concat([chart_df, new_row], ignore_index=True)

        if self._is_month_like_column(category_col):
            mn = cast(pd.Series, pd.to_numeric(chart_df[category_col], errors="coerce"))
            if mn.notna().all() and mn.between(1, 12).all():
                chart_df["__o__"] = mn.astype(int)
                chart_df = chart_df.sort_values("__o__").drop(columns=["__o__"])
                chart_df[category_col] = (
                    mn.astype(int)
                    .map(self.month_labels)
                    .fillna(chart_df[category_col])
                    .astype(str)
                )
        else:
            if chart_type in {"lingkaran", "donat"}:
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
            # Deprioritize percentage/achievement columns if they are not the only numeric columns
            if any(p in norm for p in ["persen", "percentage", "pencapaian"]):
                h -= 5
            return h, numeric_valid_counts[col]

        return max(numeric_valid_counts, key=score)

    def _pick_category_column(
        self,
        data: pd.DataFrame,
        value_column: str,
        numeric_valid_counts: dict[str, int],
    ) -> str | None:
        candidates = [c for c in data.columns if c != value_column]
        if not candidates:
            return None

        month_cands = [c for c in candidates if self._is_month_like_column(c)]
        if month_cands:
            return month_cands[0]

        hint_cands = [
            c
            for c in candidates
            if any(h in c.lower() for h in self.category_column_hints)
        ]
        if hint_cands:
            return hint_cands[0]

        non_numeric = [c for c in candidates if c not in numeric_valid_counts]
        if non_numeric:
            return non_numeric[0]

        return candidates[0]

    def _is_month_like_column(self, column_name: str) -> bool:
        return any(hint in column_name.lower() for hint in self.month_column_hints)
