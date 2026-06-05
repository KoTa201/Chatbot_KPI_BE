from uuid import UUID

from utils.constants.graphicConstants import MONTH_LABELS, SUPPORTED_CHART_TYPES, VALUE_COLUMN_HINTS
from service.graphicService import GraphicService


def test_generate_graphic_saves_png_in_session_folder(tmp_path):
    service = GraphicService(public_dir=tmp_path)
    session_id = UUID("00000000-0000-0000-0000-000000000101")

    result = service.generateGraphic(
        query_result=[
            {"bulan": 1, "total_realisasi": 120},
            {"bulan": 2, "total_realisasi": 90},
        ],
        chart_type="batang",
        session_id=session_id,
    )

    assert result.chart_type == "batang"
    assert result.image_url.startswith(
        "/public/charts/00000000-0000-0000-0000-000000000101/"
    )
    assert result.image_url.endswith(".png")

    saved_file = tmp_path / result.image_url.removeprefix("/public/")
    assert saved_file.exists()
    assert saved_file.read_bytes().startswith(b"\x89PNG")


def test_generate_graphic_maps_legacy_chart_types(tmp_path):
    service = GraphicService(public_dir=tmp_path)
    
    result = service.generateGraphic(
        query_result=[
            {"bulan": 1, "total_realisasi": 120},
            {"bulan": 2, "total_realisasi": 90},
        ],
        chart_type="bar",  # English type -> should map to "batang"
    )
    assert result.chart_type == "batang"


def test_generate_graphic_autodetect_donut(tmp_path):
    service = GraphicService(public_dir=tmp_path)
    
    # 3 categories -> should autodetect to "donat"
    result = service.generateGraphic(
        query_result=[
            {"kategori": "A", "total_realisasi": 100},
            {"kategori": "B", "total_realisasi": 120},
            {"kategori": "C", "total_realisasi": 80},
        ],
        chart_type="auto",
    )
    assert result.chart_type == "donat"


def test_graphic_service_uses_exported_constants():
    service = GraphicService()

    assert service.SUPPORTED_CHART_TYPES == SUPPORTED_CHART_TYPES
    assert service.value_column_hints == VALUE_COLUMN_HINTS
    assert service.month_labels == MONTH_LABELS
