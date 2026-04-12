"""
model/base.py
Shared enums — import dari sini untuk menghindari circular import.
"""
import enum


class AuthorityEnum(str, enum.Enum):
    HRD = "HRD"
    KARYAWAN = "Karyawan"


class RoleEnum(str, enum.Enum):
    admin = "admin"
    hrd = "hrd"
    kepala_divisi = "kepala_divisi"
    karyawan = "karyawan"


class IngestionSourceType(str, enum.Enum):
    """
    Dipakai di ingestion_logs.source_type.
    Menentukan tabel mana yang menjadi sumber ingestion.
    """
    SCHEDULER = "scheduler"
    KPI_MASTER = "kpi_master"
    KPI_TRACKER = "kpi_tracker"
