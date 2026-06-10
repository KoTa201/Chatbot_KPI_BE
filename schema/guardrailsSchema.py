"""
schema/guardrailsSchema.py
Schemas untuk SQL Wireguard Service validation results.
"""

from dataclasses import dataclass


@dataclass
class ValidationResult:
    """Result dari SQL validation oleh Wireguard Service."""
    is_valid: bool
    reason: str | None
    sanitized_sql: str | None
