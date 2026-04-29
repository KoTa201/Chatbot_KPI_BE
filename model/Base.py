"""
model/base.py
Shared enums — import dari sini untuk menghindari circular import.
"""
import enum
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class RoleEnum(str, enum.Enum):
    admin = "admin"
    kepala_divisi = "kepala_divisi"
    karyawan = "karyawan"


class AuthorityEnum(str, enum.Enum):
    """Otoritas target audience chatbot — subset dari RoleEnum."""
    HRD = "HRD"
    KARYAWAN = "Karyawan"


class GroupTypeEnum(str, enum.Enum):
    """Tipe KPIGroup: sheet master KPI atau sheet tracker realisasi."""
    MASTER = "master"
    TRACKER = "tracker"
