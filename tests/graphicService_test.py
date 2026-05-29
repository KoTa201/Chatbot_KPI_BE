from uuid import UUID

from service.graphicService import GraphicSeervice


def test_generate_graphic_saves_png_in_session_folder(tmp_path):
    service = GraphicSeervice(public_dir=tmp_path)
    session_id = UUID("00000000-0000-0000-0000-000000000101")

    result = service.generateGraphic(
        query_result=[
            {"bulan": 1, "total_realisasi": 120},
            {"bulan": 2, "total_realisasi": 90},
        ],
        chart_type="bar",
        session_id=session_id,
    )

    assert result.chart_type == "bar"
    assert result.image_url.startswith(
        "/public/charts/00000000-0000-0000-0000-000000000101/"
    )
    assert result.image_url.endswith(".png")

    saved_file = tmp_path / result.image_url.removeprefix("/public/")
    assert saved_file.exists()
    assert saved_file.read_bytes().startswith(b"\x89PNG")
