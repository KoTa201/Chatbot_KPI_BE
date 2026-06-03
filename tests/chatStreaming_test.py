import json
from types import SimpleNamespace
from uuid import UUID

import pytest

import controller.chatController as chat_controller_module
from controller.chatController import ChatController
from schema.chatSchema import ChatRequest, ChatResponse, PipelineStageInfo
from schema.clarificationSchema import ClarificationAnswerItem

SESSION_STREAM_CHAT = UUID("00000000-0000-0000-0000-000000000101")
SESSION_STREAM_CLARIFICATION = UUID("00000000-0000-0000-0000-000000000102")


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

        def process_query_stream(self, **kwargs):
            async def _stream():
                payload = expected.model_dump(mode="json")
                metadata = {key: value for key, value in payload.items() if key != "message"}
                yield f"event: metadata\ndata: {json.dumps(metadata, ensure_ascii=False)}\n\n"
                
                message = payload.get("message") or ""
                words = message.split(" ")
                chunks = [f"{w} " if i < len(words) - 1 else w for i, w in enumerate(words)] if len(words) > 1 else words if words != [""] else []
                for chunk in chunks:
                    yield f"event: message\ndata: {json.dumps({'chunk': chunk}, ensure_ascii=False)}\n\n"
                yield "event: done\ndata: {}\n\n"
            return _stream()

    monkeypatch.setattr(chat_controller_module, "ChatService", FakeChatService)

    controller = ChatController(db=None)  # type: ignore[arg-type]
    response = await controller.handle_chat(
        request=ChatRequest(message="Bagaimana KPI bulan ini?"),
        current_user=_fake_user(),  # type: ignore[arg-type]
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
        rows_returned=5,
        pipeline_stages=[PipelineStageInfo(stage="result_analysis", status="success")],
    )

    class FakeClarificationService:
        def __init__(self, db):
            self.db = db

        async def handle_clarification_response(self, **kwargs):
            captured["clarification_answers"] = kwargs["clarification_answers"]
            return SimpleNamespace(disambiguated_query="Tampilkan KPI Januari per divisi")

    class FakeChatService:
        def __init__(self, db):
            self.db = db

        async def process_query(self, **kwargs):
            captured["user_message"] = kwargs["user_message"]
            return expected

        def process_query_stream(self, **kwargs):
            captured["user_message"] = kwargs["user_message"]
            async def _stream():
                payload = expected.model_dump(mode="json")
                metadata = {key: value for key, value in payload.items() if key != "message"}
                yield f"event: metadata\ndata: {json.dumps(metadata, ensure_ascii=False)}\n\n"
                
                message = payload.get("message") or ""
                words = message.split(" ")
                chunks = [f"{w} " if i < len(words) - 1 else w for i, w in enumerate(words)] if len(words) > 1 else words if words != [""] else []
                for chunk in chunks:
                    yield f"event: message\ndata: {json.dumps({'chunk': chunk}, ensure_ascii=False)}\n\n"
                yield "event: done\ndata: {}\n\n"
            return _stream()

    monkeypatch.setattr(chat_controller_module, "ClarificationService", FakeClarificationService)
    monkeypatch.setattr(chat_controller_module, "ChatService", FakeChatService)

    controller = ChatController(db=None)
    response = await controller.handle_clarification(
        request=ChatRequest(
            message="Lanjut",
            session_id=SESSION_STREAM_CLARIFICATION,
            clarification_answers=[
                ClarificationAnswerItem(
                    question_id="00000000-0000-0000-0000-000000000201",
                    selected_option="Per divisi",
                )
            ],
        ),
        current_user=_fake_user(role="kepala_divisi"),  # type: ignore[arg-type]
    )

    events = await _read_sse_events(response)
    assert captured["user_message"] == "Tampilkan KPI Januari per divisi"
    assert captured["clarification_answers"][0].selected_option == "Per divisi"
    assert events[0][0] == "metadata"
    assert "message" not in events[0][1]

    streamed_message = "".join(
        payload["chunk"] for event_name, payload in events if event_name == "message"
    )
    assert streamed_message == expected.message
    assert events[-1][0] == "done"


@pytest.mark.asyncio
async def test_handle_clarification_streams_next_clarification_without_rag(monkeypatch):
    from schema.clarificationSchema import ClarificationMessageResponse, ClarificationQuestionResponse

    captured = {"rag_called": False}

    class FakeClarificationService:
        def __init__(self, db):
            self.db = db

        async def handle_clarification_response(self, **kwargs):
            return SimpleNamespace(
                disambiguated_query="Tampilkan ranking performa KPI",
                needs_more_clarification=True,
                clarification_message=ClarificationMessageResponse(
                    session_id=SESSION_STREAM_CLARIFICATION,
                    message_type="clarification",
                    clarifying_question="Achievement yang dimaksud metrik apa?",
                    options=["Achievement %", "Weighted score", "Lewati", "Lainnya"],
                    questions=[
                        ClarificationQuestionResponse(
                            id="q-next",
                            ambiguity_type="AmbiSchema",
                            question="Achievement yang dimaksud metrik apa?",
                            options=["Achievement %", "Weighted score", "Lewati", "Lainnya"],
                        )
                    ],
                ),
            )

    class FakeChatService:
        def __init__(self, db):
            self.db = db

        async def process_query(self, **kwargs):
            captured["rag_called"] = True
            raise AssertionError("RAG pipeline should not run when more clarification is needed")

        def process_query_stream(self, **kwargs):
            captured["rag_called"] = True
            raise AssertionError("RAG pipeline should not run when more clarification is needed")

    monkeypatch.setattr(chat_controller_module, "ClarificationService", FakeClarificationService)
    monkeypatch.setattr(chat_controller_module, "ChatService", FakeChatService)

    controller = ChatController(db=None)
    response = await controller.handle_clarification(
        request=ChatRequest(
            message="Lanjut",
            session_id=SESSION_STREAM_CLARIFICATION,
            clarification_answers=[
                ClarificationAnswerItem(question_id="q1", selected_option="Ranking tertinggi"),
            ],
        ),
        current_user=_fake_user(role="kepala_divisi"),  # type: ignore[arg-type]
    )

    events = await _read_sse_events(response)
    assert captured["rag_called"] is False
    metadata = events[0][1]
    assert "clarification_message_answer_options" not in metadata
    assert metadata["clarification_questions"][0]["question"] == "Achievement yang dimaksud metrik apa?"
    streamed_message = "".join(
        payload["chunk"] for event_name, payload in events if event_name == "message"
    )
    assert streamed_message == "Achievement yang dimaksud metrik apa?"


@pytest.mark.asyncio
async def test_handle_chat_passes_authority_role_to_service(monkeypatch):
    captured = {}
    expected = ChatResponse(
        session_id=SESSION_STREAM_CHAT,
        message="OK",
    )

    class FakeChatService:
        def __init__(self, db):
            self.db = db

        async def process_query(self, **kwargs):
            captured.update(kwargs)
            return expected

        def process_query_stream(self, **kwargs):
            captured.update(kwargs)
            async def _stream():
                yield f"event: metadata\ndata: {{}}\n\n"
                yield f"event: done\ndata: {{}}\n\n"
            return _stream()

    monkeypatch.setattr(chat_controller_module, "ChatService", FakeChatService)

    controller = ChatController(db=None)  # type: ignore[arg-type]
    await controller.handle_chat(
        request=ChatRequest(message="Tampilkan KPI saya"),
        current_user=_fake_user(role="karyawan"),  # type: ignore[arg-type]
    )

    assert captured["user_role"] == "karyawan"
