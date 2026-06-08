"""
utils/responses/sseHelpers.py
Stateless SSE event builders for streaming responses.

Extracted from chatService.py to improve cohesion and reusability.
"""

import json
from uuid import UUID
from collections.abc import AsyncIterator

from schema.chatSchema import ChatResponse, PipelineStageInfo


def message_chunks(message: str) -> list[str]:
    """Split message into word-based chunks for streaming.

    Each chunk includes trailing space except the last one.
    Returns empty list for empty messages.
    """
    if not message:
        return []
    words = message.split(" ")
    if len(words) == 1:
        return words
    chunks: list[str] = []
    last_index = len(words) - 1
    for index, word in enumerate(words):
        chunks.append(f"{word} " if index < last_index else word)
    return chunks


def format_sse_event(event_type: str, data: dict | str) -> str:
    """Format a single SSE event with proper line endings."""
    if isinstance(data, dict):
        data_str = json.dumps(data, ensure_ascii=False)
    else:
        data_str = data
    return f"event: {event_type}\ndata: {data_str}\n\n"


def format_sse_metadata(metadata: dict) -> str:
    """Format metadata as SSE event."""
    return format_sse_event("metadata", metadata)


def format_sse_chunk(chunk: str) -> str:
    """Format message chunk as SSE event."""
    return format_sse_event("message", {"chunk": chunk})


def format_sse_done() -> str:
    """Format done event."""
    return "event: done\ndata: {}\n\n"


async def emit_sse_response(
    session_id: UUID,
    stages: list[PipelineStageInfo],
    message: str,
    clarification_questions: list | None = None,
) -> AsyncIterator[str]:
    """Yield complete SSE response (metadata → message chunks → done).

    This is the main helper for emitting early-exit responses like
    clarification questions, error messages, or blocked responses.
    """
    resp = ChatResponse(
        session_id=session_id,
        message=message,
        pipeline_stages=stages,
        clarification_questions=clarification_questions,
    )
    payload = resp.model_dump(mode="json")
    metadata = {k: v for k, v in payload.items() if k != "message"}

    yield format_sse_metadata(metadata)
    for word in message_chunks(message):
        yield format_sse_chunk(word)
    yield format_sse_done()
