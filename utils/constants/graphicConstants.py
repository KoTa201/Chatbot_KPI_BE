from __future__ import annotations

import re

HEADER_WORDS = frozenset({
    "target", "realisasi", "pencapaian", "actual", "nilai",
    "kpi", "indikator", "satuan", "-", "n/a", "na", "",
})
OP_PATTERN = r"([≥≤><]|>=|<=)?"
NUM_PATTERN = r"(\d[\d.,]*)"
UNIT_PATTERN = r"\s*([a-zA-Z%/][^\s]*(?:\s+[a-zA-Z/][^\s]*)*)?"
TRL_EXACT_RE = re.compile(r"(?i)^\s*trl\s*(\d+)\s*$")
EXPR_RE = re.compile(
    r"^\s*" + OP_PATTERN + r"\s*" + NUM_PATTERN + UNIT_PATTERN + r"\s*$",
    re.UNICODE,
)
SCALE_MAP: dict[str, float] = {
    "m": 1_000_000,
    "jt": 1_000_000,
    "juta": 1_000_000,
    "k": 1_000,
    "rb": 1_000,
    "ribu": 1_000,
    "miliar": 1_000_000_000,
    "b": 1_000_000_000,
}
TRL_PATTERN = re.compile(r"(?i)trl\s*(\d+)")
COLOR_THRESHOLD_RE = re.compile(r"^\d+[–—\-]\d+%$|^[<≥≤>]=?\d+%$")
NOTES_HINTS = ("note", "notes", "keterangan", "catatan", "deskripsi", "description")
SUPPORTED_CHART_TYPES = {
    "batang", "donat", "garis",
}
VALUE_COLUMN_HINTS = (
    "total", "jumlah", "sum", "avg", "average", "rata", "nilai",
    "score", "persen", "percentage", "realisasi", "count", "qty",
    "value", "actual", "pencapaian",
)
TARGET_COLUMN_HINTS = ("target", "goal", "sasaran")
CATEGORY_COLUMN_HINTS = (
    "bulan", "month", "tanggal", "date", "periode", "nama", "kpi",
    "divisi", "kategori", "category", "label",
)
MONTH_COLUMN_HINTS = ("bulan", "bulan_num", "month", "month_num")
MONTH_LABELS = {
    1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "Mei", 6: "Jun",
    7: "Jul", 8: "Agu", 9: "Sep", 10: "Okt", 11: "Nov", 12: "Des",
}
KPI_COLUMN_HINTS = ("kpi", "nama", "kategori", "category", "produk", "product", "name", "indikator")
ACTUAL_COLUMN_HINTS = ("actual", "realisasi", "pencapaian")
