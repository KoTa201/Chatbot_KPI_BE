from __future__ import annotations

import os
from pathlib import Path
from uuid import UUID
import uuid as _uuid_module


class LocalGraphicStorage:
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


class S3GraphicStorage:
    def __init__(
        self,
        bucket: str,
        prefix: str = "charts",
        public_base_url: str = "",
        s3_client=None,
    ):
        if not bucket:
            raise ValueError("S3_CHART_BUCKET is required when CHART_STORAGE_BACKEND=s3")
        self.bucket = bucket
        self.prefix = prefix.strip("/") or "charts"
        self.public_base_url = public_base_url.rstrip("/")
        self.s3_client = s3_client or self._create_s3_client()

    def save_chart_image(self, image_bytes: bytes, session_id: UUID | None) -> str:
        folder = str(session_id) if session_id else "unsessioned"
        fname = f"{_uuid_module.uuid4()}.png"
        key = f"{self.prefix}/{folder}/{fname}"
        self.s3_client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=image_bytes,
            ContentType="image/png",
        )
        if self.public_base_url:
            return f"{self.public_base_url}/{key}"
        return f"s3://{self.bucket}/{key}"

    def _create_s3_client(self):
        import boto3

        region = os.getenv("AWS_REGION") or None
        return boto3.client("s3", region_name=region)


GraphicStorage = LocalGraphicStorage


def create_graphic_storage(public_dir: str | Path = "public", s3_client=None):
    backend = os.getenv("CHART_STORAGE_BACKEND", "local").strip().lower()
    if backend == "local":
        local_public_dir = os.getenv("CHART_LOCAL_PUBLIC_DIR") or public_dir
        return LocalGraphicStorage(public_dir=local_public_dir)
    if backend == "s3":
        return S3GraphicStorage(
            bucket=os.getenv("S3_CHART_BUCKET", ""),
            prefix=os.getenv("S3_CHART_PREFIX", "charts"),
            public_base_url=os.getenv("S3_CHART_PUBLIC_BASE_URL", ""),
            s3_client=s3_client,
        )
    raise ValueError(f"Unsupported chart storage backend: {backend}")
