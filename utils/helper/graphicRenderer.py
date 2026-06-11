from __future__ import annotations

import io
import pandas as pd
from fastapi import HTTPException, status

from utils.helper.parser.graphicParser import ParsedValue, KpiValueParser
from utils.constants.graphicConstants import TARGET_COLUMN_HINTS


class GraphicRenderer:
    """Mengurus visualisasi data ke bentuk grafik menggunakan matplotlib."""

    def __init__(self, parser: KpiValueParser, target_column_hints=TARGET_COLUMN_HINTS):
        self.parser: KpiValueParser = parser
        self.target_column_hints: list[str] = target_column_hints

    def render_simple_chart(
        self,
        df: pd.DataFrame,
        chart_type: str,
        category_col: str,
        value_col: str,
        chart_df: pd.DataFrame,
        kpi_meta: dict[str, list[ParsedValue]],
        title_prefix: str = "",
    ) -> bytes:
        plt = self._load_matplotlib_pyplot()
        fig, ax = plt.subplots(figsize=(9, 5))

        if chart_type == "batang":
            bars = ax.bar(chart_df[category_col], chart_df[value_col], color="#2563EB", label="Realisasi")
            ax.set_xlabel(category_col)
            unit_label = ""
            if value_col in kpi_meta:
                unit_label = self.parser.dominant_unit(
                    pd.Series([p.original for p in kpi_meta[value_col]])
                )
            ax.set_ylabel(f"{value_col} ({unit_label})" if unit_label else value_col)
            ax.tick_params(axis="x", rotation=30)

            # Draw target lines/markers if present
            self._draw_target_line(ax, df, chart_df, category_col, value_col)

            # Label values on top of bars
            self._draw_bar_annotations(ax, bars, chart_df, category_col, value_col, kpi_meta, df)
        elif chart_type == "garis":
            ax.plot(chart_df[category_col], chart_df[value_col], color="#2563EB", marker="o", linewidth=2, label="Realisasi")
            ax.set_xlabel(category_col)
            unit_label = ""
            if value_col in kpi_meta:
                unit_label = self.parser.dominant_unit(
                    pd.Series([p.original for p in kpi_meta[value_col]])
                )
            ax.set_ylabel(f"{value_col} ({unit_label})" if unit_label else value_col)
            ax.tick_params(axis="x", rotation=30)

            # Draw target lines/markers if present
            self._draw_target_line(ax, df, chart_df, category_col, value_col)

            # Label values above points
            self._draw_line_annotations(ax, chart_df, category_col, value_col, kpi_meta, df)
        else:  # donat or lingkaran
            pie_labels = [
                label if val > 0 else ""
                for label, val in zip(chart_df[category_col].tolist(), chart_df[value_col].tolist())
            ]
            wedges, texts, autotexts = ax.pie(
                chart_df[value_col],
                labels=pie_labels,
                autopct=lambda pct: ('%1.1f%%' % pct) if pct > 0 else '',
                startangle=90,
            )
            ax.axis("equal")
            if chart_type == "donat":
                ax.add_artist(plt.Circle((0, 0), 0.55, fc="white"))
            for wedge in wedges:
                wedge.set_linewidth(1)
                wedge.set_edgecolor("white")
            ax.legend(wedges, chart_df[category_col].tolist(), loc="best", fontsize=8)

        ax.set_title(title_prefix if title_prefix else "Visualisasi KPI")
        fig.tight_layout()
        return self._fig_to_bytes(fig, plt)

    def _draw_target_line(self, ax, df: pd.DataFrame, chart_df: pd.DataFrame, category_col: str, value_col: str) -> None:
        target_col = self._find_column_by_hints(df, self.target_column_hints)
        if target_col:
            target_series = pd.to_numeric(df[target_col], errors="coerce").dropna()
            if not target_series.empty:
                t_val = target_series.iloc[0]
                if (target_series == t_val).all():
                    ax.axhline(y=float(t_val), color="#DC2626", linestyle="--", linewidth=1.5, label=f"Target ({t_val})")
                else:
                    ax.plot(chart_df[category_col], target_series.head(len(chart_df)), color="#DC2626", linestyle="--", linewidth=1.5, label="Target")

                v_max = chart_df[value_col].max()
                t_max = target_series.max()
                max_val = max(v_max if not pd.isna(v_max) else 0, t_max)
                if max_val > 0:
                    ax.set_ylim(0, max_val * 1.15)
                ax.legend(fontsize=8)

    def _draw_bar_annotations(
        self,
        ax,
        bars,
        chart_df: pd.DataFrame,
        category_col: str,
        value_col: str,
        kpi_meta: dict[str, list[ParsedValue]],
        df: pd.DataFrame = None,
    ) -> None:
        pct_col = None
        if df is not None:
            for col in df.columns:
                col_lower = col.lower()
                if any(h in col_lower for h in ["persen", "percentage", "pencapaian"]):
                    if col_lower != value_col.lower():
                        pct_col = col
                        break

        if value_col in kpi_meta:
            meta_list = kpi_meta[value_col]
            for rect, cat in zip(bars, chart_df[category_col]):
                idx_matches = chart_df.index[chart_df[category_col] == cat].tolist()
                if idx_matches and idx_matches[0] < len(meta_list):
                    pv = meta_list[idx_matches[0]]
                    display_val = pv.display
                    
                    if pct_col is not None and idx_matches[0] < len(df):
                        pct_val = df.loc[idx_matches[0], pct_col]
                        if pd.notna(pct_val):
                            try:
                                pct_float = float(pct_val)
                                display_val = f"{display_val}\n({pct_float:.2f}%)"
                            except ValueError:
                                display_val = f"{display_val}\n({pct_val})"
                                
                    if display_val:
                        ax.text(
                            rect.get_x() + rect.get_width() / 2,
                            rect.get_height() * 1.01,
                            display_val,
                            ha="center",
                            va="bottom",
                            fontsize=7,
                        )
        else:
            for rect in bars:
                val = rect.get_height()
                label = str(int(val)) if val == int(val) else f"{val:.4g}"
                ax.text(
                    rect.get_x() + rect.get_width() / 2,
                    val * 1.01,
                    label,
                    ha="center",
                    va="bottom",
                    fontsize=7,
                )

    def _draw_line_annotations(
        self,
        ax,
        chart_df: pd.DataFrame,
        category_col: str,
        value_col: str,
        kpi_meta: dict[str, list[ParsedValue]],
        df: pd.DataFrame = None,
    ) -> None:
        pct_col = None
        if df is not None:
            for col in df.columns:
                col_lower = col.lower()
                if any(h in col_lower for h in ["persen", "percentage", "pencapaian"]):
                    if col_lower != value_col.lower():
                        pct_col = col
                        break

        for i, (cat, val) in enumerate(zip(chart_df[category_col], chart_df[value_col])):
            if pd.isna(val):
                continue
            
            display_val = ""
            if value_col in kpi_meta and i < len(kpi_meta[value_col]):
                display_val = kpi_meta[value_col][i].display
            else:
                display_val = str(int(val)) if val == int(val) else f"{val:.4g}"

            if pct_col is not None and i < len(df):
                pct_val = df.loc[i, pct_col]
                if pd.notna(pct_val):
                    try:
                        pct_float = float(pct_val)
                        display_val = f"{display_val}\n({pct_float:.2f}%)"
                    except ValueError:
                        display_val = f"{display_val}\n({pct_val})"

            if display_val:
                ax.text(
                    cat,
                    val + (ax.get_ylim()[1] * 0.02),
                    display_val,
                    ha="center",
                    va="bottom",
                    fontsize=7,
                )

    def _find_column_by_hints(self, df: pd.DataFrame, hints: tuple | list) -> str | None:
        for col in df.columns:
            if any(h in col.lower() for h in hints):
                return col
        return None

    def _fig_to_bytes(self, fig, plt) -> bytes:
        buf = io.BytesIO()
        try:
            fig.savefig(buf, format="png", dpi=140, bbox_inches="tight")
            return buf.getvalue()
        finally:
            plt.close(fig)

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
