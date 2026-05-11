"""
graphicSeervice.py
Generate visualisasi grafik dari hasil SQL untuk pipeline SRAG.
Tipe grafik yang didukung: bar, pie, donut.
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from typing import cast

import pandas as pd
from fastapi import HTTPException, status


@dataclass
class GraphicResult:
    chart_type: str
    image_base64: str


class GraphicSeervice:
    """Service untuk membuat grafik dari data hasil query SQL."""

    def __init__(self):
        self.supported_chart_types = {"bar", "pie", "donut"}
        self.value_column_hints = (
            "total",
            "jumlah",
            "sum",
            "avg",
            "average",
            "rata",
            "nilai",
            "score",
            "persen",
            "percentage",
            "realisasi",
            "target",
            "count",
            "qty",
            "value",
        )
        self.category_column_hints = (
            "bulan",
            "month",
            "tanggal",
            "date",
            "periode",
            "nama",
            "kpi",
            "divisi",
            "kategori",
            "category",
            "label",
        )
        self.month_column_hints = ("bulan", "bulan_num", "month", "month_num")
        self.month_labels = {
            1: "Januari",
            2: "Februari",
            3: "Maret",
            4: "April",
            5: "Mei",
            6: "Juni",
            7: "Juli",
            8: "Agustus",
            9: "September",
            10: "Oktober",
            11: "November",
            12: "Desember",
        }

    def generateGraphic(
        self,
        query_result: list[dict],
        chart_type: str = "bar",
    ) -> GraphicResult:
        if not query_result:
            raise ValueError("Data kosong, grafik tidak dapat dibuat.")

        chart_type = (chart_type or "bar").strip().lower()
        if chart_type not in self.supported_chart_types:
            chart_type = "bar"

        dataframe = pd.DataFrame(query_result)
        if dataframe.empty:
            raise ValueError("Data kosong, grafik tidak dapat dibuat.")

        category_col, value_col, chart_df = self._prepare_chart_data(
            dataframe=dataframe,
            chart_type=chart_type,
        )
        plt = self._load_matplotlib_pyplot()

        figure, axis = plt.subplots(figsize=(9, 5))
        try:
            if chart_type == "bar":
                axis.bar(chart_df[category_col], chart_df[value_col], color="#2563EB")
                axis.set_xlabel(category_col)
                axis.set_ylabel(value_col)
                axis.tick_params(axis="x", rotation=30)
            else:
                wedges, *_ = axis.pie(
                    chart_df[value_col],
                    labels=chart_df[category_col].to_list(),
                    autopct="%1.1f%%",
                    startangle=90,
                )
                axis.axis("equal")
                if chart_type == "donut":
                    center_circle = plt.Circle((0, 0), 0.55, fc="white")
                    axis.add_artist(center_circle)
                for wedge in wedges:
                    wedge.set_linewidth(1)
                    wedge.set_edgecolor("white")

            axis.set_title(f"Visualisasi KPI ({chart_type})")
            figure.tight_layout()

            image_buffer = io.BytesIO()
            figure.savefig(image_buffer, format="png",
                           dpi=140, bbox_inches="tight")
            image_base64 = base64.b64encode(
                image_buffer.getvalue()).decode("ascii")
        finally:
            plt.close(figure)

        return GraphicResult(chart_type=chart_type, image_base64=image_base64)

    def _prepare_chart_data(
        self,
        dataframe: pd.DataFrame,
        chart_type: str,
    ) -> tuple[str, str, pd.DataFrame]:
        data = dataframe.copy()
        data.columns = [col for col in data.columns]

        numeric_valid_counts: dict[str, int] = {}
        for column in data.columns:
            numeric_series = cast(pd.Series, pd.to_numeric(data[column], errors="coerce"))
            valid_count = numeric_series.notna().sum()
            if valid_count > 0:
                numeric_valid_counts[column] = valid_count

        best_numeric_column = self._pick_value_column(numeric_valid_counts)

        if not best_numeric_column:
            raise ValueError("Tidak ada kolom numerik untuk divisualisasikan.")

        data[best_numeric_column] = pd.to_numeric(
            data[best_numeric_column], errors="coerce")
        data = data.dropna(subset=[best_numeric_column])
        if data.empty:
            raise ValueError("Nilai numerik tidak valid untuk pembuatan grafik.")

        category_column = self._pick_category_column(
            data=data,
            value_column=best_numeric_column,
            numeric_valid_counts=numeric_valid_counts,
        )

        if not category_column:
            category_column = "__baris__"
            data[category_column] = [f"Baris {i+1}" for i in range(len(data))]

        chart_df = pd.DataFrame(data[[category_column, best_numeric_column]].copy())
        is_month_category = self._is_month_like_column(category_column)

        if is_month_category:
            month_numeric = cast(pd.Series, pd.to_numeric(chart_df[category_column], errors="coerce"))
            if month_numeric.notna().all() and month_numeric.between(1, 12).all():
                chart_df["__month_order__"] = month_numeric.astype(int)
                chart_df = chart_df.sort_values(
                    by="__month_order__", ascending=True).drop(columns=["__month_order__"])
                chart_df[category_column] = month_numeric.astype(int).map(
                    self.month_labels).fillna(chart_df[category_column]).astype(str)
            else:
                chart_df[category_column] = chart_df[category_column].astype(str)
        else:
            chart_df[category_column] = chart_df[category_column].astype(str)
            if chart_type in {"pie", "donut"}:
                chart_df = chart_df.sort_values(
                    by=best_numeric_column, ascending=False)

        chart_df = chart_df.head(12)
        return category_column, best_numeric_column, chart_df

    def _pick_value_column(self, numeric_valid_counts: dict[str, int]) -> str | None:
        if not numeric_valid_counts:
            return None

        def score(column_name: str) -> tuple[int, int]:
            normalized = column_name.lower()
            hint_score = sum(1 for hint in self.value_column_hints if hint in normalized)
            if self._is_month_like_column(column_name):
                hint_score -= 2
            return hint_score, numeric_valid_counts[column_name]

        prioritized = sorted(
            numeric_valid_counts.keys(),
            key=score,
            reverse=True,
        )
        return prioritized[0]

    def _pick_category_column(
        self,
        data: pd.DataFrame,
        value_column: str,
        numeric_valid_counts: dict[str, int],
    ) -> str | None:
        candidate_columns = [column for column in data.columns if column != value_column]
        if not candidate_columns:
            return None

        month_candidates = [
            col for col in candidate_columns if self._is_month_like_column(col)
        ]
        if month_candidates:
            return month_candidates[0]

        hint_candidates = [
            col for col in candidate_columns
            if any(hint in col.lower() for hint in self.category_column_hints)
        ]
        if hint_candidates:
            return hint_candidates[0]

        non_numeric_candidates = [
            col for col in candidate_columns if col not in numeric_valid_counts
        ]
        if non_numeric_candidates:
            return non_numeric_candidates[0]

        return candidate_columns[0]

    def _is_month_like_column(self, column_name: str) -> bool:
        normalized = column_name.lower()
        return any(hint in normalized for hint in self.month_column_hints)

    @staticmethod
    def _load_matplotlib_pyplot():
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            return plt
        except ImportError as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Matplotlib belum tersedia untuk generate visualisasi.",
            ) from error
