"""
utils/datetime.py
Centralized datetime utilities for UTC operations.
"""

from datetime import datetime, timezone


def utc_now() -> datetime:
    """Return current UTC datetime with timezone info."""
    return datetime.now(timezone.utc)
