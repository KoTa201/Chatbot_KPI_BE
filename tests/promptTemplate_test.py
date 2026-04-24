from datetime import datetime

from template.promptTemplate import build_analysis_prompt


def test_build_analysis_prompt_supports_datetime_values():
    query_result = [
        {
            "nama_kpi": "Peningkatan Penjualan",
            "terakhir_diperbarui": datetime(2026, 4, 18, 10, 30, 45),
        }
    ]

    prompt = build_analysis_prompt(
        user_query="Tampilkan data KPI terbaru",
        executed_sql="SELECT * FROM kpi_tracker_records LIMIT 1;",
        query_result=query_result,
        rows_count=1,
    )

    assert "2026-04-18T10:30:45" in prompt
