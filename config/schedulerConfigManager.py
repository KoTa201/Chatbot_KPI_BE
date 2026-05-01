"""
config/schedulerConfigManager.py

Thread-safe (async-safe) singleton manager untuk konfigurasi scheduler.
Menyimpan konfigurasi ke file JSON di root project, bukan database.

JSON Schema yang divalidasi saat baca:
  - id          : string (UUID)
  - interval_value : string (ISO-8601 datetime)
  - is_enabled  : boolean
  - last_run_at : string|null (ISO-8601 datetime)
  - next_run_at : string|null (ISO-8601 datetime)
  - created_at  : string (ISO-8601 datetime)
  - updated_at  : string (ISO-8601 datetime)
"""

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from model.SchedulerConfig import SchedulerConfigModel

# ─── Lokasi file JSON (absolut, relatif ke direktori file ini → root project) ──
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_FILEPATH = _PROJECT_ROOT / "scheduler_config.json"

# ─── JSON Schema sederhana untuk validasi saat baca ────────────────────────────
_CONFIG_SCHEMA: dict = {
    "type": "object",
    "required": ["id", "interval_value", "is_enabled", "created_at", "updated_at"],
    "properties": {
        "id":             {"type": "string"},
        "interval_value": {"type": ["string", "null"]},
        "is_enabled":     {"type": "boolean"},
        "last_run_at":    {"type": ["string", "null"]},
        "next_run_at":    {"type": ["string", "null"]},
        "created_at":     {"type": "string"},
        "updated_at":     {"type": "string"},
    },
    "additionalProperties": False,
}


def _validate_schema(data: dict) -> None:
    """
    Validasi ringan terhadap _CONFIG_SCHEMA tanpa dependensi eksternal.
    Melempar ValueError jika data tidak valid.
    """
    if not isinstance(data, dict):
        raise ValueError("Config harus berupa objek JSON.")

    required = _CONFIG_SCHEMA.get("required", [])
    for field in required:
        if field not in data:
            raise ValueError(f"Field wajib '{field}' tidak ditemukan di config file.")

    props = _CONFIG_SCHEMA.get("properties", {})
    for field, rule in props.items():
        if field not in data:
            continue
        value = data[field]
        allowed_types = rule.get("type", [])
        if isinstance(allowed_types, str):
            allowed_types = [allowed_types]

        # Map JSON schema type → Python type
        type_map = {
            "string":  str,
            "boolean": bool,
            "null":    type(None),
            "object":  dict,
            "array":   list,
            "number":  (int, float),
            "integer": int,
        }
        python_types = tuple(
            t for name in allowed_types
            if (t := type_map.get(name)) is not None
        )
        if python_types and not isinstance(value, python_types):
            raise ValueError(
                f"Field '{field}' diharapkan bertipe {allowed_types}, "
                f"diperoleh {type(value).__name__}."
            )

    extra_keys = set(data) - set(props)
    if extra_keys and _CONFIG_SCHEMA.get("additionalProperties") is False:
        raise ValueError(
            f"Field tidak dikenal ditemukan di config: {extra_keys}"
        )


class SchedulerConfigManager:
    """
    Singleton manager yang membaca/menulis konfigurasi scheduler dari/ke file JSON.
    Menggunakan asyncio.Lock untuk keamanan akses paralel (async-safe).
    """

    _lock: asyncio.Lock = asyncio.Lock()
    _filepath: Path = _DEFAULT_FILEPATH

    # ─── Public class methods ─────────────────────────────────────────────── #

    @classmethod
    async def get_config(cls) -> SchedulerConfigModel:
        """Baca config dari JSON file secara async-safe."""
        async with cls._lock:
            return await asyncio.to_thread(cls._read_file)

    @classmethod
    async def save_config(cls, config: SchedulerConfigModel) -> None:
        """Tulis config ke JSON file secara atomic dan async-safe."""
        async with cls._lock:
            await asyncio.to_thread(cls._write_file, config)

    @classmethod
    def set_filepath(cls, path: Path) -> None:
        """Override lokasi file (berguna untuk testing)."""
        cls._filepath = path

    # ─── Private sync helpers (dijalankan di thread pool) ────────────────── #

    @classmethod
    def _default_config(cls) -> SchedulerConfigModel:
        """Buat konfigurasi default: setiap tanggal 28, jam 00:00 UTC."""
        now = datetime.now()
        return SchedulerConfigModel(
            id=uuid4(),
            # Tahun/bulan pada interval_value diabaikan; hanya day & hour yang dipakai CronTrigger.
            interval_value=datetime(1900, 1, 28, 0, 0, 0),
            is_enabled=True,
            last_run_at=None,
            next_run_at=None,
            created_at=now,
            updated_at=now,
        )

    @classmethod
    def _read_file(cls) -> SchedulerConfigModel:
        if not cls._filepath.exists():
            # Belum ada file → buat & simpan default config
            default = cls._default_config()
            cls._write_file(default)
            return default
        try:
            with open(cls._filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            _validate_schema(data)
            return SchedulerConfigModel(**data)
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            # File korup atau schema tidak valid → reset ke default
            import logging
            logging.getLogger(__name__).warning(
                "scheduler_config.json tidak valid, direset ke default: %s", exc
            )
            default = cls._default_config()
            cls._write_file(default)
            return default

    @classmethod
    def _write_file(cls, config: SchedulerConfigModel) -> None:
        """Tulis atomik menggunakan file sementara lalu os.replace."""
        # Pydantic v2: model_dump_json menghasilkan JSON string yang benar
        data_json = config.model_dump_json()

        tmp_path = cls._filepath.with_suffix(".json.tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(data_json)
            os.replace(tmp_path, cls._filepath)
        except Exception:
            # Hapus file sementara jika terjadi kesalahan
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            raise
