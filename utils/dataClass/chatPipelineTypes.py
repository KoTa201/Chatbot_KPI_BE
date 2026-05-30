"""
service/chatPipelineTypes.py
Shared dataclass for the chat pipeline execution context.

Extracted from chatService.py as part of the service refactor to
improve testability and separate pipeline state from orchestration.
"""

from dataclasses import dataclass
from uuid import UUID


@dataclass
class ChatPipelineContext:
    """Holds the mutable state accumulated across pipeline stages."""

    session_id: UUID
    user_id: UUID
    user_role: str
    user_query: str

    generated_sql: str | None = None
    wireguard_status: str | None = None
    wireguard_reason: str | None = None
    execution_status: str | None = None
    rows_returned: int | None = None
    execution_time_ms: int | None = None
