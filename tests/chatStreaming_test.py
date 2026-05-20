import json
from types import SimpleNamespace
from uuid import UUID

SESSION_STREAM_CHAT = UUID("00000000-0000-0000-0000-000000000101")
SESSION_STREAM_CLARIFICATION = UUID("00000000-0000-0000-0000-000000000102")

import pytest

import controller.chatController as chat_controller_module
from controller.chatController import ChatController
from schema.chatSchema import ChatRequest, ChatResponse, PipelineStageInfo


def _fake_user(role: str = "admin"):
    return SimpleNamespace(
        id="0f5b6dd9-3275-452f-b7dd-c62e309fd329",
        role=SimpleNamespace(value=role),
    )


async def _read_sse_events(streaming_response):
    chunks: list[str] = []
    async for chunk in streaming_response.body_iterator:
        chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)

    body = "".join(chunks)
    events: list[tuple[str, dict]] = []
    for block in body.split("\n\n"):
        if not block.strip():
            continue

        event_name = ""
        data_payload: dict = {}
        for line in block.splitlines():
            if line.startswith("event: "):
                event_name = line.replace("event: ", "", 1).strip()
            elif line.startswith("data: "):
                data_payload = json.loads(line.replace("data: ", "", 1).strip())

        events.append((event_name, data_payload))
    return events


@pytest.mark.asyncio
async def test_handle_chat_returns_stream_with_message_words(monkeypatch):
    expected = ChatResponse(
        session_id=SESSION_STREAM_CHAT,
        message="Analisa KPI bulan ini menunjukkan peningkatan.",
        generated_sql="SELECT 1;",
        rows_returned=1,
        execution_time_ms=120,
        pipeline_stages=[PipelineStageInfo(stage="result_analysis", status="success")],
    )

    class FakeChatService:
        def __init__(self, db):
            self.db = db

        async def process_query(self, **kwargs):
            return expected

    monkeypatch.setattr(chat_controller_module, "ChatService", FakeChatService)

    controller = ChatController(db=None)
    response = await controller.handle_chat(
        request=ChatRequest(message="Bagaimana KPI bulan ini?"),
        current_user=_fake_user(),
    )

    assert response.media_type == "text/event-stream"
    events = await _read_sse_events(response)

    assert events[0][0] == "metadata"
    metadata = events[0][1]
    assert metadata["session_id"] == str(SESSION_STREAM_CHAT)
    assert metadata["generated_sql"] == "SELECT 1;"
    assert "message" not in metadata

    message_chunks = [
        payload["chunk"] for event_name, payload in events if event_name == "message"
    ]
    streamed_message = "".join(message_chunks)
    assert streamed_message == expected.message
    assert message_chunks == [
        "Analisa ",
        "KPI ",
        "bulan ",
        "ini ",
        "menunjukkan ",
        "peningkatan.",
    ]
    assert events[-1][0] == "done"


@pytest.mark.asyncio
async def test_handle_clarification_streams_message_and_keeps_metadata_non_stream(monkeypatch):
    captured = {}
    expected = ChatResponse(
        session_id=SESSION_STREAM_CLARIFICATION,
        message="Baik, saya tampilkan KPI per divisi untuk bulan Januari.",
        clarification_message_answer_options=None,
        rows_returned=5,
        pipeline_stages=[PipelineStageInfo(stage="result_analysis", status="success")],
    )

    class FakeClarificationService:
        def __init__(self, db):
            self.db = db

        async def handle_clarification_response(self, session_id: UUID, clarification_answer: str):
            return SimpleNamespace(disambiguated_query="Tampilkan KPI Januari per divisi")

    class FakeChatService:
        def __init__(self, db):
            self.db = db

        async def process_query(self, **kwargs):
            captured["user_message"] = kwargs["user_message"]
            return expected

    monkeypatch.setattr(chat_controller_module, "ClarificationService", FakeClarificationService)
    monkeypatch.setattr(chat_controller_module, "ChatService", FakeChatService)

    controller = ChatController(db=None)
    response = await controller.handle_clarification(
        request=ChatRequest(
            message="Lanjut",
            session_id=SESSION_STREAM_CLARIFICATION,
            clarification_answer="Per divisi",
        ),
        current_user=_fake_user(role="kepala_divisi"),
    )

    events = await _read_sse_events(response)
    assert captured["user_message"] == "Tampilkan KPI Januari per divisi"
    assert events[0][0] == "metadata"
    assert "message" not in events[0][1]

    streamed_message = "".join(
        payload["chunk"] for event_name, payload in events if event_name == "message"
    )
    assert streamed_message == expected.message
    assert events[-1][0] == "done"
