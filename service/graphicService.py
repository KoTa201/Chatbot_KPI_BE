"""
graphicService.py
Generate visualisasi grafik dari hasil SQL untuk pipeline SRAG.
Orkestrator utama yang mengoordinasikan data preparation, rendering, dan storage.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pandas as pd

from utils.constants.graphicConstants import (
    MONTH_LABELS,
    SUPPORTED_CHART_TYPES,
)
from service.graphicParser import (
    ParsedValue,
    _KPI_PARSER,
)
from service.graphicPreparer import GraphicDataPreparer
from service.graphicRenderer import GraphicRenderer
from service.graphicStorage import GraphicStorage


class GraphicResult:
    def __init__(self, chart_type: str, image_url: str, kpi_name: str = ""):
        self.chart_type = chart_type
        self.image_url = image_url
        self.kpi_name = kpi_name


class GraphicService:
    """Service untuk membuat grafik dari data hasil query SQL."""

    SUPPORTED_CHART_TYPES = SUPPORTED_CHART_TYPES

    def __init__(self, public_dir: str | Path = "public"):
        self.parser = _KPI_PARSER
        self.preparer = GraphicDataPreparer(parser=self.parser, month_labels=MONTH_LABELS)
        self.renderer = GraphicRenderer(parser=self.parser)
        self.storage = GraphicStorage(public_dir=public_dir)

        # Re-export variables for compatibility with external references / tests
        self.value_column_hints = self.preparer.value_column_hints
        self.target_column_hints = self.preparer.target_column_hints
        self.category_column_hints = self.preparer.category_column_hints
        self.month_column_hints = self.preparer.month_column_hints
        self.month_labels = MONTH_LABELS

        self.chart_type_map = {
            "bar": "batang",
            "batang": "batang",
            "donut": "donat",
            "donat": "donat",
            "line": "garis",
            "garis": "garis",
        }

    def _normalize_chart_type(
        self,
        chart_type: str | None,
        df: pd.DataFrame,
        kpi_meta: dict[str, list[ParsedValue]] | None = None,
    ) -> str:
        chart_type = (chart_type or "").strip().lower()
        mapped = self.chart_type_map.get(chart_type)
        if mapped:
            return mapped
        return self._auto_detect_chart_type(df, kpi_meta)

    def _auto_detect_chart_type(
        self,
        df: pd.DataFrame,
        kpi_meta: dict[str, list[ParsedValue]] | None = None,
    ) -> str:
        try:
            category_col = self.preparer._pick_category_column(df, "", {})
            if category_col and self.preparer._is_month_like_column(category_col):
                return "garis"

            numeric_valid_counts = {}
            for col in df.columns:
                n = int(pd.to_numeric(df[col], errors="coerce").notna().sum())
                if n > 0:
                    numeric_valid_counts[col] = n
            value_col = self.preparer._pick_value_column(numeric_valid_counts)
            if value_col:
                category_col = self.preparer._pick_category_column(
                    df, value_col, numeric_valid_counts
                )
                if category_col and category_col in df.columns:
                    num_unique = df[category_col].nunique()
                    if 2 <= num_unique <= 5:
                        return "donat"
        except Exception:
            pass
        return "batang"

    # Public entry point
    def generateGraphic(
        self,
        query_result: list[dict],
        chart_type: str = "batang",
        session_id: UUID | None = None,
    ) -> GraphicResult:
        if not query_result:
            raise ValueError("Data kosong, grafik tidak dapat dibuat.")

        raw_df = pd.DataFrame(query_result)
        if raw_df.empty:
            raise ValueError("Data kosong, grafik tidak dapat dibuat.")

        df = self.preparer.drop_non_data_columns(raw_df)
        df, kpi_meta = self.preparer.parse_kpi_columns(df)
        chart_type = self._normalize_chart_type(chart_type, df, kpi_meta)

        category_col, value_col, chart_df = self.preparer.prepare_chart_data(df, chart_type)

        image_bytes = self.renderer.render_simple_chart(
            df=df,
            chart_type=chart_type,
            category_col=category_col,
            value_col=value_col,
            chart_df=chart_df,
            kpi_meta=kpi_meta,
        )

        image_url = self.storage.save_chart_image(image_bytes=image_bytes, session_id=session_id)
        return GraphicResult(chart_type=chart_type, image_url=image_url)

    def generateGraphicPerKpi(
        self,
        query_result: list[dict],
        chart_type: str = "batang",
        session_id: UUID | None = None,
    ) -> list[GraphicResult]:
        if not query_result:
            raise ValueError("Data kosong, grafik tidak dapat dibuat.")

        raw_df = pd.DataFrame(query_result)
        if raw_df.empty:
            raise ValueError("Data kosong, grafik tidak dapat dibuat.")

        df = self.preparer.drop_non_data_columns(raw_df)
        df, kpi_meta = self.preparer.parse_kpi_columns(df)
        chart_type = self._normalize_chart_type(chart_type, df, kpi_meta)

        from utils.constants.graphicConstants import KPI_COLUMN_HINTS
        kpi_cols = []
        other_cols = []
        for col in df.columns:
            col_lower = col.lower()
            if any(h in col_lower for h in KPI_COLUMN_HINTS):
                if not any(h in col_lower for h in self.value_column_hints + self.target_column_hints + self.month_column_hints):
                    if pd.to_numeric(df[col], errors='coerce').notna().mean() < 0.5:
                        if 'kpi' in col_lower or 'indikator' in col_lower:
                            kpi_cols.append(col)
                        else:
                            other_cols.append(col)
        group_cols = kpi_cols + other_cols

        if not group_cols:
            kpi_col = self._pick_kpi_column(df)
            if kpi_col is None or df[kpi_col].nunique() <= 1:
                single = self.generateGraphic(query_result, chart_type, session_id)
                return [single]
            df['__group__'] = df[kpi_col].astype(str)
            df = df.sort_values(by=kpi_col)
        else:
            df = df.sort_values(by=group_cols)
            df['__group__'] = df[group_cols].astype(str).agg(' - '.join, axis=1)

        kpi_col = '__group__'

        if df[kpi_col].nunique() <= 1:
            single = self.generateGraphic(query_result, chart_type, session_id)
            return [single]

        kpi_order = list(dict.fromkeys(df[kpi_col].dropna().astype(str).tolist()))
        results: list[GraphicResult] = []

        for kpi_name in kpi_order:
            mask = df[kpi_col].astype(str) == kpi_name
            subset = df[mask].copy()
            if subset.empty:
                continue

            subset = subset.drop(columns=['__group__'])
            subset_meta = self._slice_meta(kpi_meta, list(subset.index))

            sub_chart_type = self._auto_detect_chart_type(subset, subset_meta)

            try:
                category_col, value_col, chart_df = self.preparer.prepare_chart_data(subset, sub_chart_type)
                image_bytes = self.renderer.render_simple_chart(
                    df=subset.reset_index(drop=True),
                    chart_type=sub_chart_type,
                    category_col=category_col,
                    value_col=value_col,
                    chart_df=chart_df,
                    kpi_meta=subset_meta,
                    title_prefix=kpi_name,
                )
                image_url = self.storage.save_chart_image(image_bytes, session_id)
                results.append(
                    GraphicResult(
                        chart_type=sub_chart_type,
                        image_url=image_url,
                        kpi_name=kpi_name,
                    )
                )
            except Exception as exc:
                import warnings
                warnings.warn(f"Gagal render KPI '{kpi_name}': {exc}")
                continue

        if not results:
            single = self.generateGraphic(query_result, chart_type, session_id)
            return [single]

        return results

    def _slice_meta(
        self,
        kpi_meta: dict[str, list[ParsedValue]],
        orig_indices: list[int],
    ) -> dict[str, list[ParsedValue]]:
        result: dict[str, list[ParsedValue]] = {}
        for col, pv_list in kpi_meta.items():
            result[col] = [pv_list[i] for i in orig_indices if i < len(pv_list)]
        return result

    def _pick_kpi_column(
        self, df: pd.DataFrame, exclude: list[str | None] | None = None
    ) -> str | None:
        excl = [c for c in (exclude or []) if c]
        from utils.constants.graphicConstants import KPI_COLUMN_HINTS
        for col in df.columns:
            if col not in excl and any(h in col.lower() for h in KPI_COLUMN_HINTS):
                return col
        for col in df.columns:
            if col not in excl:
                if pd.to_numeric(df[col], errors="coerce").isna().mean() > 0.5:
                    return col
        return None
