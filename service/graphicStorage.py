from __future__ import annotations

from pathlib import Path
from uuid import UUID
import uuid as _uuid_module


class GraphicStorage:
    """Mengurus penyimpanan file gambar grafik ke local storage."""

    def __init__(self, public_dir: str | Path = "public"):
        self.public_dir = Path(public_dir)

    def save_chart_image(self, image_bytes: bytes, session_id: UUID | None) -> str:
        folder = str(session_id) if session_id else "unsessioned"
        fname = f"{_uuid_module.uuid4()}.png"
        rel = Path("charts") / folder / fname
        out = self.public_dir / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(image_bytes)
        return f"/public/{rel.as_posix()}"
