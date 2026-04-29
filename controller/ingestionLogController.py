"""
controller/ingestionLogController.py
Controller untuk menangani ingestion log endpoints.

Responsibilities:
  - Validate request parameters (limit, group_type)
  - Enforce business rules (max limit)
  - Call service untuk fetch dan transform logs
  - Handle error handling dan HTTP responses
  - Orchestrate request/response flow
"""

from datetime import date
from typing import Literal, Optional

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from service.ingestionLogService import IngestionLogService


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_LIMIT = 20
MAX_LIMIT = 100

VALID_GROUP_TYPES = {"tracker", "master"}


class IngestionLogController:
    """Controller untuk ingestion log operations."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.service = IngestionLogService(db)

    # ─────────────────────────────────────────────────────────────────────────
    # PUBLIC: Get ingestion logs
    # ─────────────────────────────────────────────────────────────────────────

    async def get_ingestion_logs(
        self,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
        group_type: Optional[Literal["tracker", "master"]] = None,
        status: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> dict:
        """
        Get ingestion logs dengan optional filtering.

        Args:
            limit: Jumlah logs yang dikembalikan (max 100)
            offset: Posisi awal data untuk pagination
            group_type: Filter berdasarkan jenis KPI ("tracker" atau "master")

        Returns:
            {
                "total": int,
                "logs": [...]
            }

        Raises:
            HTTPException: 400 jika parameter invalid
            HTTPException: 500 jika terjadi error saat fetch dari database
        """
        # ── Validate limit ──────────────────────────────────────────────
        try:
            limit = self._validate_limit(limit)
            offset = self._validate_offset(offset)
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=str(e),
            )

        # ── Validate group_type ────────────────────────────────────────
        if group_type is not None and group_type not in VALID_GROUP_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"group_type harus salah satu dari {VALID_GROUP_TYPES} atau None. Diterima: {group_type}",
            )

        # ── Fetch logs dari service ────────────────────────────────────
        try:
            result = await self.service.get_ingestion_logs(
                limit=limit,
                offset=offset,
                group_type=group_type,
                status=status,
                start_date=start_date,
                end_date=end_date,
            )
            return result

        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Error saat fetch ingestion logs: {str(e)}",
            )

    # ─────────────────────────────────────────────────────────────────────────
    # PRIVATE: Validation helpers
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _validate_limit(limit: int) -> int:
        """
        Validate dan normalize limit parameter.

        Args:
            limit: Jumlah logs yang diminta

        Returns:
            Normalized limit (clamped ke [1, MAX_LIMIT])

        Raises:
            ValueError: Jika limit invalid
        """
        if not isinstance(limit, int):
            raise ValueError(
                f"limit harus berupa integer. Diterima: {type(limit).__name__}")

        if limit < 1:
            raise ValueError(f"limit harus >= 1. Diterima: {limit}")

        if limit > MAX_LIMIT:
            limit = MAX_LIMIT

        return limit

    @staticmethod
    def _validate_offset(offset: int) -> int:
        if not isinstance(offset, int):
            raise ValueError(
                f"offset harus berupa integer. Diterima: {type(offset).__name__}")

        if offset < 0:
            raise ValueError(f"offset harus >= 0. Diterima: {offset}")

        return offset
