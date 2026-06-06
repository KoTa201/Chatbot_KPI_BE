"""
tests/clarificationMechanism_test.py
Test suite untuk Clarification Question Mechanism (LLM-based only).
Berdasarkan skenario di PRD Section 8.
"""

import json
from utils.sessionContextManager import SessionContextManager
from template.promptTemplate import (
    build_ambiguity_assessment_prompt,
    build_clarification_choice_generation_prompt,
    build_query_disambiguation_prompt,
    build_scope_policy_assessment_prompt,
)
from schema.clarificationSchema import (
    AmbiguityAssessmentResult,
    DetectedAmbiguity,
    BatchedClarificationResponse,
    ClarificationAnswerItem,
    ClarificationQuestionResponse,
    PRD_AMBIGUITY_TYPES,
)
import pytest
from uuid import UUID, uuid4
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.future import select
from sqlalchemy.pool import StaticPool

from databaseConfig import Base
from model.ChatMessage import ChatMessage
from model.ChatSession import ChatSession
from model.ClarificationAnswerOption import ClarificationAnswerOption
from model.ClarificationQuestion import ClarificationQuestion
from model.User import User, RoleEnum
from service.ambiguityDetectorService import AmbiguityDetectorService
from service.clarificationService import ClarificationService
from repository.clarificationRepository import ClarificationRepository
from repository.chatMessageRepository import ChatMessageRepository
from service.chatService import ChatService

SESSION_TEST_1 = UUID("00000000-0000-0000-0000-000000000201")
SESSION_TEST_2 = UUID("00000000-0000-0000-0000-000000000202")
SESSION_TEST_3 = UUID("00000000-0000-0000-0000-000000000203")
SESSION_TEST_4 = UUID("00000000-0000-0000-0000-000000000204")
SESSION_TEST_5 = UUID("00000000-0000-0000-0000-000000000205")
SESSION_TEST_6 = UUID("00000000-0000-0000-0000-000000000206")
SESSION_TEST_7 = UUID("00000000-0000-0000-0000-000000000207")
SESSION_TEST_8 = UUID("00000000-0000-0000-0000-000000000208")


async def _make_sqlite_session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(
        bind=engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, session_factory


async def _create_user_and_session(db: AsyncSession, session_id: UUID):
    user = User(
        username=f"user_{uuid4().hex[:8]}",
        email=f"user_{uuid4().hex[:8]}@example.com",
        full_name="Test User",
        hashed_password="hashed",
        role=RoleEnum.karyawan,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    db.add(ChatSession(session_id=session_id, user_id=user.id, session_name="Test"))
    await db.commit()
    return user


def test_clarification_question_has_level1_source_column():
    """Test that ClarificationQuestion has is_ambiguity_level1_type_llm column."""
    from model.ClarificationQuestion import ClarificationQuestion
    column = ClarificationQuestion.__table__.columns.get(
        "is_ambiguity_level1_type_llm")
    assert column is not None
    assert column.nullable is True


def test_clarification_question_has_no_ambiguous_phrase_column():
    """ClarificationQuestion no longer persists ambiguous phrase."""
    from model.ClarificationQuestion import ClarificationQuestion

    assert ClarificationQuestion.__table__.columns.get("ambiguous_phrase") is None


def test_clarification_question_has_no_user_answer_column():
    """ClarificationQuestion no longer persists numeric user answer."""
    from model.ClarificationQuestion import ClarificationQuestion

    assert ClarificationQuestion.__table__.columns.get("user_answer") is None


def test_clarification_question_has_no_answer_options_column():
    """ClarificationQuestion no longer stores serialized answer options."""
    from model.ClarificationQuestion import ClarificationQuestion

    assert ClarificationQuestion.__table__.columns.get("answer_options") is None


def test_clarification_answer_option_table_shape():
    """Clarification answer options are stored as ordered child rows."""
    from model.ClarificationAnswerOption import ClarificationAnswerOption

    columns = ClarificationAnswerOption.__table__.columns

    assert columns.get("id") is not None
    assert columns.get("clarification_question_id") is not None
    assert columns.get("option_text") is not None
    assert columns.get("option_order") is not None
    assert columns["clarification_question_id"].nullable is False
    assert columns["option_text"].nullable is False
    assert columns["option_order"].nullable is False


def test_clarification_question_response_excludes_ambiguous_phrase():
    """ClarificationQuestionResponse schema excludes ambiguous_phrase from response."""
    from schema.clarificationSchema import ClarificationQuestionResponse

    response = ClarificationQuestionResponse(
        id="q1",
        ambiguity_type="AmbiSchema",
        question="Metrik mana yang dimaksud?",
        options=["Achievement %", "Total realisasi"],
    )

    assert "ambiguous_phrase" not in response.model_dump()


class TestAmbiguityDetectorLLM:
    """Test suite untuk LLM-based ambiguity detection."""

    @pytest.mark.asyncio
    async def test_llm_detects_ambiguity(self):
        """Test LLM-based detection mendeteksi ambiguitas."""
        detector = AmbiguityDetectorService()

        # Mock LLM response untuk ambiguous query
        with patch.object(detector.llm, 'call_model', new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = '''{
                "is_ambiguous": true,
                "ambiguity_type": "scope",
                "possible_interpretations": [
                    "Per individu",
                    "Per divisi"
                ],
                "suggested_clarifying_question": "Anda ingin data per individu atau per divisi?",
                "answer_options": ["Per individu", "Per divisi", "Seluruh perusahaan"]
            }'''

            result = await detector.detect_ambiguity(
                "Siapa yang performa terbaik?",
                "Owner"
            )

            assert result.is_ambiguous is True
            assert result.ambiguity_type == "scope"
            assert result.detection_source == "llm"
            assert len(result.answer_options) == 3

    @pytest.mark.asyncio
    async def test_llm_clear_query(self):
        """Test LLM menganggap query yang jelas sebagai tidak ambiguous."""
        detector = AmbiguityDetectorService()

        with patch.object(detector.llm, 'call_model', new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = '''{
                "is_ambiguous": false,
                "ambiguity_type": "none",
                "possible_interpretations": [],
                "suggested_clarifying_question": null,
                "answer_options": []
            }'''

            result = await detector.detect_ambiguity(
                "Tampilkan semua KPI Januari 2025 per divisi",
                "Owner"
            )

            assert result.is_ambiguous is False
            assert result.ambiguity_type == "none"

    @pytest.mark.asyncio
    async def test_llm_json_in_markdown_fence(self):
        """Test parser tetap menerima JSON di dalam markdown code fence."""
        detector = AmbiguityDetectorService()

        with patch.object(detector.llm, 'call_model', new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = '''```json
            {
                "is_ambiguous": true,
                "ambiguity_type": "scope",
                "possible_interpretations": [
                    "Per individu",
                    "Per divisi"
                ],
                "suggested_clarifying_question": "Per individu atau per divisi?",
                "answer_options": ["Per individu", "Per divisi"]
            }
            ```'''

            result = await detector.detect_ambiguity(
                "Siapa yang performa terbaik?",
                "Owner"
            )

            assert result.is_ambiguous is True
            assert result.ambiguity_type == "scope"

    @pytest.mark.asyncio
    async def test_legacy_boolean_result_is_not_overridden_by_score(self):
        """Legacy score must not override the LLM ambiguity decision."""
        detector = AmbiguityDetectorService()

        with patch.object(detector.llm, 'call_model', new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = '''{
                "is_ambiguous": true,
                "ambiguity_type": "scope",
                "possible_interpretations": [],
                "suggested_clarifying_question": "Scope tidak jelas",
                "answer_options": ["Per individu", "Per divisi"]
            }'''

            result = await detector.detect_ambiguity(
                "Berapa KPI?",
                "Owner"
            )

            assert result.is_ambiguous is True

    @pytest.mark.asyncio
    async def test_llm_api_error_fallback(self):
        """Test fallback behavior ketika LLM API error."""
        detector = AmbiguityDetectorService()

        with patch.object(detector.llm, 'call_model', new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = Exception("503 Service Unavailable")

            result = await detector.detect_ambiguity(
                "Siapa yang terbaik?",
                "Owner"
            )

            # Should fall back to NOT ambiguous (safe default)
            assert result.is_ambiguous is False
            assert result.detection_source == "llm_fallback"

    @pytest.mark.asyncio
    async def test_llm_invalid_json_fallback(self):
        """Test fallback ketika LLM return invalid JSON."""
        detector = AmbiguityDetectorService()

        with patch.object(detector.llm, 'call_model', new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = "Invalid JSON response"

            result = await detector.detect_ambiguity(
                "Siapa karyawan terbaik?",
                "Owner"
            )

            # Should fall back to NOT ambiguous
            assert result.is_ambiguous is False
            assert result.detection_source == "llm_fallback"


class TestClarificationService:
    """Test suite untuk clarification service orchestration."""

    @pytest.mark.asyncio
    async def test_process_user_query_flushes_clarification_questions(self):
        engine, session_factory = await _make_sqlite_session()
        session_id = uuid4()
        try:
            async with session_factory() as db:
                await _create_user_and_session(db, session_id)
                service = ClarificationService(db)
                service.ambiguity_detector.detect_ambiguity = AsyncMock(return_value=AmbiguityAssessmentResult(
                    is_ambiguous=True,
                    ambiguity_type="AmbiSchema",
                    detection_source="llm",
                    detected_ambiguities=[
                        DetectedAmbiguity(
                            ambiguity_type="AmbiSchema",
                            suggested_clarifying_question="Metrik mana?",
                            answer_options=["Achievement %", "Realisasi"],
                        )
                    ],
                ))

                result = await service.process_user_query(
                    user_query="Tampilkan KPI terbaik",
                    user_role="karyawan",
                    session_id=session_id,
                )

                assert result is not None
                stored = (await db.execute(select(ClarificationQuestion).where(
                    ClarificationQuestion.session_id == session_id
                ))).scalars().all()
                assert len(stored) == 1
                assert stored[0].clarification_question == "Metrik mana?"
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_process_query_stores_original_query_message_when_clarifying(self):
        engine, session_factory = await _make_sqlite_session()
        session_id = uuid4()
        try:
            async with session_factory() as db:
                user = await _create_user_and_session(db, session_id)
                service = ChatService(db)
                service.chatbot_service.get_active_chatbot_for_role = AsyncMock(
                    return_value=SimpleNamespace(id=uuid4(), addon_prompt=None)
                )
                # Mock session_service methods
                service.session_service.create_chatbot_message = AsyncMock()
                with patch.object(ClarificationService, "process_user_query", new_callable=AsyncMock) as mock_process:
                    mock_process.return_value = SimpleNamespace(
                        clarifying_question="Metrik mana?",
                        options=["Achievement %", "Realisasi", "Lewati", "Lainnya"],
                        questions=[],
                        is_out_of_scope=False,
                    )
                    stream = service.process_query_stream(
                        user_message="Tampilkan KPI terbaik",
                        user_id=user.id,
                        user_role="karyawan",
                        session_id=session_id,
                    )
                    # Collect SSE stream to consume it (triggers side effects)
                    messages = []
                    async for event in stream:
                        messages.append(event)

                # Check the SSE metadata contains the clarification prompt message
                combined = "".join(messages)
                assert "clarification" in combined.lower() or "Metrik" in combined

            async with session_factory() as db:
                stored = (await db.execute(select(ChatMessage).where(
                    ChatMessage.session_id == session_id,
                    ChatMessage.is_sender_chatbot.is_(False),
                ))).scalars().all()
                assert [message.message for message in stored] == ["Tampilkan KPI terbaik"]
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_process_query_does_not_store_refined_query_message(self):
        engine, session_factory = await _make_sqlite_session()
        session_id = uuid4()
        try:
            async with session_factory() as db:
                user = await _create_user_and_session(db, session_id)
                original_message = ChatMessage(
                    session_id=session_id,
                    message="Tampilkan KPI terbaik",
                    is_sender_chatbot=False,
                )
                db.add(original_message)
                await db.commit()

                service = ChatService(db)
                service.chatbot_service.get_active_chatbot_for_role = AsyncMock(
                    return_value=SimpleNamespace(id=uuid4(), addon_prompt=None)
                )
                service.session_service.create_session_if_missing = AsyncMock()
                service.session_service.create_user_message = AsyncMock(
                    return_value=SimpleNamespace(message_id=uuid4())
                )
                service.session_service.create_chatbot_message = AsyncMock()

                from schema.wireguardSchema import ValidationResult

                service.llm_service.generate_sql = AsyncMock(return_value="SELECT 1")
                service.llm_service.decide_visualization_request = AsyncMock(
                    return_value=SimpleNamespace(is_visualize=False, chart_type=None)
                )
                service.wireguard_service.validate = Mock(
                    return_value=ValidationResult(
                        is_valid=True, reason=None, sanitized_sql="SELECT 1",
                    )
                )
                service._run_sql_execution_stage = AsyncMock(return_value=([{"value": 1}], 1))

                async def fake_analyze(prompt):
                    yield "Hasil KPI"

                service.llm_service.analyze_result_stream = fake_analyze
                messages = []
                stream = service.process_query_stream(
                    user_message="Tampilkan KPI terbaik dengan Achievement %",
                    user_id=user.id,
                    user_role="karyawan",
                    session_id=session_id,
                    context_from_clarification=SimpleNamespace(disambiguated_query="Tampilkan KPI terbaik dengan Achievement %"),
                )
                async for event in stream:
                    messages.append(event)

                # Verify message was streamed
                combined = "".join(messages)
                assert "Hasil KPI" in combined

            async with session_factory() as db:
                stored = (await db.execute(select(ChatMessage).where(
                    ChatMessage.session_id == session_id,
                    ChatMessage.is_sender_chatbot.is_(False),
                ))).scalars().all()
                assert [message.message for message in stored] == ["Tampilkan KPI terbaik"]
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_process_user_query_returns_batched_questions(self):
        service = ClarificationService(db=None)
        service.repo.create = AsyncMock(side_effect=[
            SimpleNamespace(clarification_question_id="q1"),
            SimpleNamespace(clarification_question_id="q2"),
        ])

        service.llm._call_llm = AsyncMock(side_effect=[
            json.dumps({"choices": ["Achievement %", "Realisasi", "Abstain", "Others"]}),
            json.dumps({"choices": ["Calendar Year 2025", "Fiscal Year 2025", "Abstain", "Others"]}),
        ])

        with patch.object(service.ambiguity_detector, 'detect_ambiguity', new_callable=AsyncMock) as mock_detect:
            mock_detect.return_value = AmbiguityAssessmentResult(
                is_ambiguous=True,
                ambiguity_type="AmbiSchema",
                detection_source="llm",
                detected_ambiguities=[
                    DetectedAmbiguity(
                        ambiguity_type="AmbiSchema",
                        suggested_clarifying_question="Metrik terbaik mana?",
                        answer_options=["Achievement %", "Realisasi"],
                    ),
                    DetectedAmbiguity(
                        ambiguity_type="AmbiRef",
                        suggested_clarifying_question="Periode tahun lalu mana?",
                        answer_options=[
                            "Calendar Year 2025", "Fiscal Year 2025"],
                    ),
                ],
            )

            result = await service.process_user_query(
                user_query="Tampilkan sales terbaik tahun lalu",
                user_role="Kepala Divisi",
                session_id=SESSION_TEST_2,
            )

        assert result is not None
        assert result.questions is not None
        assert len(result.questions) == 2
        assert result.questions[0].options[-2:] == ["Lewati", "Lainnya"]
        assert service.repo.create.await_count == 2

    @pytest.mark.asyncio
    async def test_generate_clarifying_question_always_uses_cq_generation_llm(self):
        service = ClarificationService(db=None)
        service.llm._call_llm = AsyncMock(return_value=json.dumps({
            "choices": [
                "achievement::kpi_tracker, gunakan persentase pencapaian KPI",
                "actual_value::kpi_tracker, gunakan nilai aktual KPI",
                "Abstain",
                "Others",
            ]
        }))

        result = await service._generate_clarifying_question(
            ambiguity_type="AmbiSchema",
            suggested_question="Metrik mana yang dimaksud?",
            suggested_options=[
                "kpi_tracker::achievement, persentase pencapaian KPI",
                "kpi_tracker::actual_value, nilai aktual KPI",
            ],
            metadata={"level_1_label": "Database-sourced ambiguity"},
        )

        assert service.llm._call_llm.await_count == 1
        assert result.clarifying_question == "Metrik mana yang dimaksud?"
        assert result.options == [
            "achievement::kpi_tracker, gunakan persentase pencapaian KPI",
            "actual_value::kpi_tracker, gunakan nilai aktual KPI",
            "Lewati",
            "Lainnya",
        ]

    @pytest.mark.asyncio
    async def test_generate_clarifying_question_accepts_fenced_json_from_cq_generation_llm(self):
        service = ClarificationService(db=None)
        service.llm._call_llm = AsyncMock(return_value='''```json
{"choices": ["Achievement — gunakan persentase pencapaian KPI", "Nilai Aktual — gunakan nilai aktual KPI"]}
```''')

        result = await service._generate_clarifying_question(
            ambiguity_type="AmbiSchema",
            suggested_question="Metrik mana yang dimaksud?",
            suggested_options=[
                "kpi_tracker::achievement, persentase pencapaian KPI",
                "kpi_tracker::actual_value, nilai aktual KPI",
            ],
            metadata={},
        )

        assert service.llm._call_llm.await_count == 1
        assert result.options == [
            "Achievement — gunakan persentase pencapaian KPI",
            "Nilai Aktual — gunakan nilai aktual KPI",
            "Lewati",
            "Lainnya",
        ]

    @pytest.mark.asyncio
    async def test_generate_clarifying_question_falls_back_to_detector_options_when_cq_generation_fails(self):
        service = ClarificationService(db=None)
        service.llm._call_llm = AsyncMock(side_effect=RuntimeError("LLM unavailable"))

        result = await service._generate_clarifying_question(
            ambiguity_type="AmbiView",
            suggested_question="Perkembangan ingin dilihat dari aspek apa?",
            suggested_options=[
                "Pencapaian KPI per periode",
                "Tren performa dari waktu ke waktu",
            ],
            metadata={},
        )

        assert service.llm._call_llm.await_count == 1
        assert result.options == [
            "Pencapaian KPI per periode",
            "Tren performa dari waktu ke waktu",
            "Lewati",
            "Lainnya",
        ]

    @pytest.mark.asyncio
    async def test_handle_clarification_response_rewrites_from_batched_answers(self):
        service = ClarificationService(db=SimpleNamespace(commit=AsyncMock()))
        service.repo.get_by_session = AsyncMock(return_value=[
            SimpleNamespace(
                clarification_question_id="q1",
                clarification_question="Metrik terbaik mana?",
            ),
            SimpleNamespace(
                clarification_question_id="q2",
                clarification_question="Periode mana?",
            ),
        ])
        service.repo.update_with_answer = AsyncMock()
        service.chat_message_repo.get_recent_by_session_id = AsyncMock(return_value=[])
        service.ambiguity_detector.detect_ambiguity = AsyncMock(return_value=AmbiguityAssessmentResult(
            is_ambiguous=False,
            ambiguity_type="none",
            detected_ambiguities=[],
        ))

        with patch.object(service.llm, '_call_llm', new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = "Tampilkan sales dengan Achievement % tertinggi untuk Calendar Year 2025 hanya divisi aktif"

            result = await service.handle_clarification_response(
                session_id=SESSION_TEST_2,
                clarification_answers=[
                    ClarificationAnswerItem(
                        question_id="q1", selected_option="Achievement %"),
                    ClarificationAnswerItem(
                        question_id="q2", selected_option="Calendar Year 2025"),
                ],
                additional_constraints="hanya divisi aktif",
            )

        assert "Achievement %" in result.disambiguated_query
        assert "Calendar Year 2025" in result.disambiguated_query
        assert service.repo.update_with_answer.await_count == 2

    @pytest.mark.asyncio
    async def test_handle_clarification_response_uses_preference_tree_additional_information(self):
        service = ClarificationService(db=SimpleNamespace(commit=AsyncMock()))
        service.repo.get_by_session = AsyncMock(return_value=[
            SimpleNamespace(
                clarification_question_id="q1",
                ambiguity_type="AmbiSchema",
                clarification_question="'Terbaik' merujuk ke metrik apa?",
            ),
            SimpleNamespace(
                clarification_question_id="q2",
                ambiguity_type="AmbiRef",
                clarification_question="'Tahun lalu' merujuk ke periode mana?",
            ),
        ])
        service.repo.update_with_answer = AsyncMock()
        service.chat_message_repo.get_recent_by_session_id = AsyncMock(return_value=[])
        service.ambiguity_detector.detect_ambiguity = AsyncMock(return_value=AmbiguityAssessmentResult(
            is_ambiguous=False,
            ambiguity_type="none",
            detected_ambiguities=[],
        ))

        captured_prompt = {}

        async def fake_call_llm(**kwargs):
            captured_prompt["prompt"] = kwargs["prompt"]
            return "Tampilkan sales dengan Achievement % tertinggi hanya divisi aktif"

        service.llm._call_llm = fake_call_llm

        result = await service.handle_clarification_response(
            session_id=SESSION_TEST_2,
            clarification_answers=[
                ClarificationAnswerItem(
                    question_id="q1", selected_option="Achievement %"),
                ClarificationAnswerItem(
                    question_id="q2", selected_option="Lewati"),
            ],
            additional_constraints="hanya divisi aktif",
            original_query="Tampilkan sales terbaik tahun lalu",
        )

        assert result.disambiguated_query == "Tampilkan sales dengan Achievement % tertinggi hanya divisi aktif"
        assert result.needs_more_clarification is False
        assert "Achievement %" in captured_prompt["prompt"]
        assert "hanya divisi aktif" not in captured_prompt["prompt"]
        assert "Lewati" not in captured_prompt["prompt"]
        assert result.preference_tree is not None
        # Lewati answers are excluded from build_qa_set, so the 'Tahun lalu'
        # question only has the leaf placeholder but no answer entry
        tree_leaves = result.preference_tree
        # Verify the tree exists but Lewati is not recorded as a preference
        ref_children = tree_leaves.get("children", {}).get("AmbiRef", {}).get("children", {})
        ref_q_key = "'Tahun lalu' merujuk ke periode mana?"
        if ref_q_key in ref_children:
            qa_list = ref_children[ref_q_key].get("children", {}).get("leaf", {}).get("qa_list", [])
            assert all(qa.get("answer") != "Lewati" for qa in qa_list)

    @pytest.mark.asyncio
    async def test_build_recent_conversation_information_prepends_history_and_skips_current_query(self):
        service = ClarificationService(db=None)
        service.chat_message_repo.get_recent_by_session_id = AsyncMock(return_value=[
            SimpleNamespace(is_sender_chatbot=False, message="Tampilkan KPI Sales"),
            SimpleNamespace(is_sender_chatbot=True, message="KPI Sales mencapai 90%"),
            SimpleNamespace(is_sender_chatbot=False, message="Perjelas periode"),
        ])

        result = await service._build_recent_conversation_information(
            session_id=SESSION_TEST_2,
            source_query="Perjelas periode",
            additional_information="- Metrik mana yang dimaksud?: Achievement %",
        )

        assert result == (
            "[RIWAYAT PERCAKAPAN TERBARU]\n"
            "- User: Tampilkan KPI Sales\n"
            "- Chatbot: KPI Sales mencapai 90%\n"
            "\n"
            "- Metrik mana yang dimaksud?: Achievement %"
        )
        service.chat_message_repo.get_recent_by_session_id.assert_awaited_once_with(
            session_id=SESSION_TEST_2,
            limit=6,
        )

    @pytest.mark.asyncio
    async def test_build_recent_conversation_information_marks_summary_followup_as_resolved_context(self):
        service = ClarificationService(db=None)
        service.chat_message_repo.get_recent_by_session_id = AsyncMock(return_value=[
            SimpleNamespace(
                is_sender_chatbot=False,
                message="Bandingkan pencapaian KPI Andi dan Adiansyah untuk semua bulan di tahun 2025",
            ),
            SimpleNamespace(
                is_sender_chatbot=True,
                message="Berikut adalah persentase pencapaian KPI antara Andi dan Adiansyah untuk semua bulan di tahun 2025: Bulan 1 ... Bulan 12 ...",
            ),
        ])

        result = await service._build_recent_conversation_information(
            session_id=SESSION_TEST_2,
            source_query="Coba simpulkan siapa yang lebih baik",
        )

        assert "[RIWAYAT PERCAKAPAN TERBARU]" in result
        assert "Bandingkan pencapaian KPI Andi dan Adiansyah" in result
        assert "tahun 2025" in result.lower()
        assert "semua bulan" in result.lower()

    @pytest.mark.asyncio
    async def test_build_recent_conversation_information_returns_existing_info_when_history_empty(self):
        service = ClarificationService(db=None)
        service.chat_message_repo.get_recent_by_session_id = AsyncMock(return_value=[])

        result = await service._build_recent_conversation_information(
            session_id=SESSION_TEST_2,
            source_query="Tampilkan KPI",
            additional_information="- Periode mana yang dimaksud?: Q1 2025",
        )

        assert result == "- Periode mana yang dimaksud?: Q1 2025"

    @pytest.mark.asyncio
    async def test_handle_clarification_response_does_not_repeat_answered_questions(self):
        service = ClarificationService(db=SimpleNamespace(commit=AsyncMock()))
        service.repo.get_by_session = AsyncMock(return_value=[
            SimpleNamespace(
                clarification_question_id="q1",
                ambiguity_type="AmbiIntent",
                clarification_question="Progress KPI Akmal ingin dilihat dari sisi apa?",
            ),
            SimpleNamespace(
                clarification_question_id="q2",
                ambiguity_type="AmbiValue",
                clarification_question="Akmal merujuk ke karyawan atau KPI yang mana?",
            ),
        ])
        service.repo.update_with_answer = AsyncMock()
        service.repo.create = AsyncMock()
        service.chat_message_repo.get_recent_by_session_id = AsyncMock(return_value=[])
        service.llm._call_llm = AsyncMock(
            return_value="Progress KPI Akmal berdasarkan persentase pencapaian terhadap target untuk karyawan bernama Akmal"
        )
        service.ambiguity_detector.detect_ambiguity = AsyncMock(return_value=AmbiguityAssessmentResult(
            is_ambiguous=True,
            ambiguity_type="AmbiIntent",
            detection_source="llm",
            detected_ambiguities=[
                DetectedAmbiguity(
                    ambiguity_type="AmbiIntent",
                    suggested_clarifying_question="Progress KPI Akmal ingin dilihat dari sisi apa?",
                    answer_options=["Realisasi KPI terbaru", "Persentase pencapaian terhadap target"],
                ),
                DetectedAmbiguity(
                    ambiguity_type="AmbiValue",
                    suggested_clarifying_question="Akmal merujuk ke karyawan atau KPI yang mana?",
                    answer_options=["Karyawan bernama Akmal", "KPI yang mengandung kata Akmal"],
                ),
            ],
        ))

        result = await service.handle_clarification_response(
            session_id=SESSION_TEST_2,
            clarification_answers=[
                ClarificationAnswerItem(
                    question_id="q1",
                    selected_option="Persentase pencapaian terhadap target",
                ),
                ClarificationAnswerItem(
                    question_id="q2",
                    selected_option="Karyawan bernama Akmal",
                ),
            ],
            original_query="Seberapa jauh perkembangan progress kpi akmal?",
        )

        assert result.needs_more_clarification is False
        assert result.clarification_message is None
        service.repo.create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_handle_clarification_response_does_not_repeat_same_ambiguity_type_with_different_wording(self):
        service = ClarificationService(db=SimpleNamespace(commit=AsyncMock()))
        service.repo.get_by_session = AsyncMock(return_value=[
            SimpleNamespace(
                clarification_question_id="q1",
                ambiguity_type="AmbiView",
                clarification_question="Aspek apa yang ingin Anda bandingkan dalam pencapaian KPI antara Andi dan Adiansyah?",
                selected_answer=None,
            ),
        ])
        service.repo.update_with_answer = AsyncMock()
        service.repo.create = AsyncMock()
        service.chat_message_repo.get_recent_by_session_id = AsyncMock(return_value=[])
        service.llm._call_llm = AsyncMock(
            return_value="Bandingkan Andi dan Adiansyah berdasarkan pencapaian KPI per bulan terhadap target"
        )
        service.ambiguity_detector.detect_ambiguity = AsyncMock(return_value=AmbiguityAssessmentResult(
            is_ambiguous=True,
            ambiguity_type="AmbiView",
            detection_source="llm",
            detected_ambiguities=[
                DetectedAmbiguity(
                    ambiguity_type="AmbiView",
                    suggested_clarifying_question="Aspek apa yang ingin Anda bandingkan antara Andi dan Adiansyah?",
                    answer_options=["Pencapaian KPI per bulan", "Tren performa"],
                ),
            ],
        ))

        result = await service.handle_clarification_response(
            session_id=SESSION_TEST_2,
            clarification_answers=[
                ClarificationAnswerItem(
                    question_id="q1",
                    selected_option="Pencapaian KPI per bulan — membandingkan target vs nilai aktual setiap bulan untuk melihat seberapa baik Andi dan Adiansyah memenuhi tujuan bulanan mereka",
                ),
            ],
            original_query="Bandingkan pencapaian KPI Andi dan Adiansyah",
        )

        assert result.needs_more_clarification is False
        assert result.clarification_message is None
        service.repo.create.assert_not_awaited()
        service.ambiguity_detector.detect_ambiguity.assert_awaited_once()
        recheck_kwargs = service.ambiguity_detector.detect_ambiguity.await_args.kwargs
        assert "Pencapaian KPI per bulan" in recheck_kwargs["session_context"]

    @pytest.mark.asyncio
    async def test_handle_clarification_response_uses_recent_history_from_chat_message_repository(self):
        service = ClarificationService(db=SimpleNamespace(commit=AsyncMock()))
        service.repo.get_by_session = AsyncMock(return_value=[
            SimpleNamespace(
                clarification_question_id="q1",
                ambiguity_type="AmbiSchema",
                clarification_question="Metrik mana yang dimaksud?",
            ),
        ])
        service.repo.update_with_answer = AsyncMock()
        service.chat_message_repo.get_recent_by_session_id = AsyncMock(return_value=[
            SimpleNamespace(is_sender_chatbot=False, message="Tampilkan KPI Sales"),
            SimpleNamespace(is_sender_chatbot=True, message="KPI Sales mencapai 90%"),
        ])
        service.ambiguity_detector.detect_ambiguity = AsyncMock(return_value=AmbiguityAssessmentResult(
            is_ambiguous=False,
            ambiguity_type="none",
            detected_ambiguities=[],
        ))
        captured_prompt = {}

        async def fake_call_llm(**kwargs):
            captured_prompt["prompt"] = kwargs["prompt"]
            return "Tampilkan achievement KPI Sales"

        service.llm._call_llm = fake_call_llm

        result = await service.handle_clarification_response(
            session_id=SESSION_TEST_2,
            clarification_answers=[
                ClarificationAnswerItem(question_id="q1", selected_option="Achievement %"),
            ],
            original_query="Achievement KPI Sales?",
        )

        assert result.disambiguated_query == "Tampilkan achievement KPI Sales"
        assert "[RIWAYAT PERCAKAPAN TERBARU]" in captured_prompt["prompt"]
        assert "- User: Tampilkan KPI Sales" in captured_prompt["prompt"]
        assert "- Chatbot: KPI Sales mencapai 90%" in captured_prompt["prompt"]
        service.chat_message_repo.get_recent_by_session_id.assert_awaited_once_with(
            session_id=SESSION_TEST_2,
            limit=6,
        )

    @pytest.mark.asyncio
    async def test_handle_clarification_response_returns_next_questions_when_recheck_is_ambiguous(self):
        service = ClarificationService(db=SimpleNamespace(commit=AsyncMock()))
        service.repo.get_by_session = AsyncMock(return_value=[
            SimpleNamespace(
                clarification_question_id="q1",
                ambiguity_type="AmbiIntent",
                clarification_question="Performa ingin dilihat sebagai ranking atau ringkasan?",
                selected_answer=None,
            ),
        ])
        service.repo.update_with_answer = AsyncMock()
        service.repo.create = AsyncMock(
            return_value=SimpleNamespace(clarification_question_id="q-next"))
        service.chat_message_repo.get_recent_by_session_id = AsyncMock(return_value=[])
        service.llm._call_llm = AsyncMock(
            return_value="Tampilkan ranking performa KPI berdasarkan achievement")
        service.ambiguity_detector.detect_ambiguity = AsyncMock(return_value=AmbiguityAssessmentResult(
            is_ambiguous=True,
            ambiguity_type="AmbiSchema",
            detection_source="llm",
            detected_ambiguities=[
                DetectedAmbiguity(
                    ambiguity_type="AmbiSchema",
                    suggested_clarifying_question="Achievement yang dimaksud metrik apa?",
                    answer_options=["Achievement %", "Weighted score"],
                )
            ],
        ))

        result = await service.handle_clarification_response(
            session_id=SESSION_TEST_2,
            clarification_answers=[
                ClarificationAnswerItem(
                    question_id="q1", selected_option="Ranking tertinggi"),
            ],
            original_query="Tampilkan performa KPI",
        )

        assert result.needs_more_clarification is True
        assert result.clarification_message is not None
        assert result.clarification_message.questions[0].question == "Achievement yang dimaksud metrik apa?"

    @pytest.mark.asyncio
    async def test_process_direct_answer_no_ambiguity(self):
        """Test direct answer ketika query tidak ambiguous."""
        service = ClarificationService(db=None)
        service.repo.create = AsyncMock(
            return_value=SimpleNamespace(id=uuid4()))

        # Mock ambiguity detection to return NOT ambiguous
        with patch.object(
            service.ambiguity_detector,
            'detect_ambiguity',
            new_callable=AsyncMock
        ) as mock_detect:
            mock_detect.return_value = AmbiguityAssessmentResult(
                is_ambiguous=False,
                ambiguity_type="none",
                possible_interpretations=[],
                suggested_clarifying_question=None,
                answer_options=[],
                detection_source="llm"
            )

            result = await service.process_user_query(
                user_query="Tampilkan semua KPI Januari 2025",
                user_role="Owner",
                session_id=SESSION_TEST_1,
            )

            assert result is None
            service.repo.create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_process_clarification_needed(self):
        """Test clarification diperlukan ketika query ambiguous."""
        service = ClarificationService(db=None)
        service.repo.create = AsyncMock(
            return_value=SimpleNamespace(clarification_question_id=uuid4()))
        service.llm._call_llm = AsyncMock(return_value=json.dumps({
            "choices": ["Per individu", "Per divisi", "Abstain", "Others"]
        }))

        with patch.object(
            service.ambiguity_detector,
            'detect_ambiguity',
            new_callable=AsyncMock
        ) as mock_detect:
            mock_detect.return_value = AmbiguityAssessmentResult(
                is_ambiguous=True,
                ambiguity_type="scope",
                detection_source="llm",
                detected_ambiguities=[
                    DetectedAmbiguity(
                        ambiguity_type="scope",
                        suggested_clarifying_question="Scope mana yang Anda maksud?",
                        answer_options=["Per individu", "Per divisi"],
                    )
                ]
            )

            result = await service.process_user_query(
                user_query="Siapa yang terbaik?",
                user_role="Owner",
                session_id=SESSION_TEST_2,
            )

            assert result is not None
            assert result.message_type == "clarification"
            assert result.clarifying_question == (
                "Terdapat beberapa pertanyaan yang ingin saya tanyakan terkait, silakan jawab pertanyaan berikut."
                "\n1. Scope mana yang Anda maksud?"
            )
            assert result.options == ["Per individu",
                                      "Per divisi", "Lewati", "Lainnya"]

    @pytest.mark.asyncio
    async def test_max_clarification_limit(self):
        """Test max clarification limit per session."""
        ctx_manager = SessionContextManager()
        session_id = SESSION_TEST_3

        # Add 2 clarifications (max)
        ctx_manager.add_clarification_to_history(
            session_id,
            question="Pertanyaan 1",
            answer="Jawaban 1",
            ambiguity_type="scope"
        )
        ctx_manager.add_clarification_to_history(
            session_id,
            question="Pertanyaan 2",
            answer="Jawaban 2",
            ambiguity_type="temporal"
        )

        # Check count
        history = ctx_manager.get_clarification_history(session_id)
        assert len(history) == 2


class TestSessionContextManager:
    """Test suite untuk session context management."""

    def test_create_session_context(self):
        """Test create new session context."""
        manager = SessionContextManager()
        session_id = SESSION_TEST_4

        ctx = manager.get_session_context(session_id)
        assert ctx is not None
        assert ctx["session_id"] == session_id
        assert len(ctx["clarification_history"]) == 0

    def test_add_clarification_to_history(self):
        """Test add clarification to session history."""
        manager = SessionContextManager()
        session_id = SESSION_TEST_5

        manager.add_clarification_to_history(
            session_id,
            question="Berapa KPI?",
            answer="Per bulan",
            ambiguity_type="temporal"
        )

        ctx = manager.get_session_context(session_id)
        assert len(ctx["clarification_history"]) == 1
        assert ctx["clarification_history"][0]["question"] == "Berapa KPI?"

    def test_scope_preference_storage(self):
        """Test store scope preference dari clarification answer."""
        manager = SessionContextManager()
        session_id = SESSION_TEST_6

        manager.set_scope_preference(session_id, "scope", "Per divisi")

        ctx = manager.get_session_context(session_id)
        assert ctx["scope_preferences"].get("scope") == "Per divisi"

    def test_preference_persistence_across_queries(self):
        """Test scope preference persist across multiple queries."""
        manager = SessionContextManager()
        session_id = SESSION_TEST_7

        # Store preference
        manager.set_scope_preference(session_id, "scope", "Per divisi")

        # Add multiple clarifications
        manager.add_clarification_to_history(session_id, "Q1", "A1", "scope")
        manager.add_clarification_to_history(
            session_id, "Q2", "A2", "temporal")

        # Check preference still there
        ctx = manager.get_session_context(session_id)
        assert ctx["scope_preferences"].get("scope") == "Per divisi"

    def test_session_ttl_cleanup(self):
        """Test session TTL cleanup mechanism."""
        manager = SessionContextManager()
        session_id = SESSION_TEST_8

        # Create context
        manager.get_session_context(session_id)
        assert manager.get_stats()["active_sessions"] >= 1

        # Access again
        manager.get_session_context(session_id)
        assert manager.get_stats()["active_sessions"] >= 1


class TestScenarios:
    """Test suite untuk end-to-end scenarios."""

    @pytest.mark.asyncio
    async def test_scenario_llm_ambiguous_query(self):
        """Skenario: LLM mendeteksi ambiguitas dan generate pertanyaan."""
        detector = AmbiguityDetectorService()

        with patch.object(detector.llm, 'call_model', new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = '''{
                "is_ambiguous": true,
                "ambiguity_type": "scope",
                "possible_interpretations": ["Per individu", "Per divisi"],
                "suggested_clarifying_question": "Apakah Anda ingin data per individu atau per divisi?",
                "answer_options": ["Per individu", "Per divisi", "Seluruh perusahaan"]
            }'''

            result = await detector.detect_ambiguity(
                "Siapa yang performa terbaik?",
                "Owner"
            )

            assert result.is_ambiguous is True
            assert result.ambiguity_type == "scope"

    @pytest.mark.asyncio
    async def test_scenario_no_ambiguity(self):
        """Skenario: LLM menganggap query sudah jelas."""
        detector = AmbiguityDetectorService()

        with patch.object(detector.llm, 'call_model', new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = '''{
                "is_ambiguous": false,
                "ambiguity_type": "none",
                "possible_interpretations": [],
                "suggested_clarifying_question": null,
                "answer_options": []
            }'''

            result = await detector.detect_ambiguity(
                "Tampilkan semua KPI Januari 2025 per divisi untuk status achieve",
                "Owner"
            )

            assert result.is_ambiguous is False

    @pytest.mark.asyncio
    async def test_scenario_score_does_not_override_llm_decision(self):
        """Skenario: score legacy tidak mengubah keputusan ambiguity dari LLM."""
        detector = AmbiguityDetectorService()

        with patch.object(detector.llm, 'call_model', new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = '''{
                "is_ambiguous": true,
                "ambiguity_type": "scope",
                "possible_interpretations": [{"text": "Per individu"}, {"text": "Per divisi"}],
                "suggested_clarifying_question": "Scope tidak jelas",
                "answer_options": ["Per individu", "Per divisi"]
            }'''

            result = await detector.detect_ambiguity(
                "Data KPI",
                "Owner"
            )

            assert result.is_ambiguous is True

    @pytest.mark.asyncio
    async def test_scenario_llm_unavailable(self):
        """Skenario: LLM tidak tersedia, fallback to safe default."""
        detector = AmbiguityDetectorService()

        with patch.object(detector.llm, 'call_model', new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = Exception("503: Service Unavailable")

            result = await detector.detect_ambiguity(
                "Siapa yang terbaik?",
                "Owner"
            )

            # Should fallback gracefully
            assert result.is_ambiguous is False
            assert result.detection_source == "llm_fallback"


class TestPRDSchemas:
    """Test suite for PRD-aligned schema models."""

    def test_prd_ambiguity_types_cover_all_seven_types(self):
        assert PRD_AMBIGUITY_TYPES == {
            "AmbiSchema",
            "AmbiValue",
            "AmbiIntent",
            "AmbiSource",
            "AmbiContext",
            "AmbiFallacy",
            "AmbiRef",
            "none",
        }

    def test_detected_ambiguity_schema_accepts_prd_taxonomy(self):
        ambiguity = DetectedAmbiguity(
            ambiguity_type="AmbiSchema",
            possible_interpretations=[
                {"interpretation": "achievement percentage"}],
            suggested_clarifying_question="'Terbaik' merujuk ke metrik apa?",
            answer_options=["Achievement %", "Total realisasi"],
            metadata={"candidate_columns": [
                "achievement_percentage", "realization"]},
        )

        assert ambiguity.ambiguity_type == "AmbiSchema"
        assert ambiguity.metadata["candidate_columns"] == [
            "achievement_percentage",
            "realization",
        ]

    def test_batched_clarification_response_schema(self):
        response = BatchedClarificationResponse(
            session_id=SESSION_TEST_1,
            questions=[
                ClarificationQuestionResponse(
                    id="q1",
                    ambiguity_type="AmbiSchema",
                    question="'Terbaik' merujuk ke metrik apa?",
                    options=["Achievement %",
                             "Total realisasi", "Lewati", "Lainnya"],
                    metadata={"source": "llm"},
                )
            ],
        )

        assert response.message_type == "clarification"
        assert response.questions[0].options[-2:] == ["Lewati", "Lainnya"]

    def test_clarification_answer_item_uses_free_text_for_lainnya(self):
        answer = ClarificationAnswerItem(
            question_id="q1",
            selected_option="Lainnya",
            free_text="Gunakan weighted achievement score",
        )

        assert answer.question_id == "q1"
        assert answer.free_text == "Gunakan weighted achievement score"


@pytest.mark.asyncio
async def test_llm_detects_multiple_prd_ambiguities():
    detector = AmbiguityDetectorService()

    with patch.object(detector.llm, 'call_model', new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = '''{
            "is_ambiguous": true,
            "detected_ambiguities": [
                {
                    "ambiguity_type": "AmbiSchema",
                    "possible_interpretations": [{"interpretation": "achievement percentage"}],
                    "suggested_clarifying_question": "'Terbaik' merujuk ke metrik apa?",
                    "answer_options": ["Achievement %", "Total realisasi"],
                    "metadata": {"candidate_columns": ["achievement_percentage", "realization"]}
                },
                {
                    "ambiguity_type": "AmbiRef",
                    "possible_interpretations": [{"interpretation": "calendar year"}],
                    "suggested_clarifying_question": "'Tahun lalu' merujuk ke periode mana?",
                    "answer_options": ["Calendar Year 2025", "Fiscal Year 2025"],
                    "metadata": {}
                }
            ]
        }'''

        result = await detector.detect_ambiguity(
            "Tampilkan sales terbaik tahun lalu",
            "Kepala Divisi",
            "KPI context",
        )

    assert result.is_ambiguous is True
    assert result.ambiguity_type == "AmbiSchema"
    assert len(result.detected_ambiguities) == 2
    assert result.detected_ambiguities[1].ambiguity_type == "AmbiRef"


class TestKPIAmbiguityContext:
    """Test suite for KPI ambiguity context builder."""

    def test_kpi_ambiguity_context_contains_domain_terms(self):
        from template.promptTemplate import build_context

        context = build_context()

        assert "KPI Master" in context
        assert "KPI Tracker" in context
        assert "target" in context.lower()
        assert "realisasi" in context.lower()
        assert "achievement" in context.lower()

    def test_kpi_ambiguity_context_is_bounded(self):
        from template.promptTemplate import build_context

        context = build_context()

        assert len(context) < 4000


@pytest.mark.asyncio
async def test_detector_passes_raw_options_without_normalizing_cq_defaults(monkeypatch):
    from service.ambiguityDetectorService import AmbiguityDetectorService

    service = AmbiguityDetectorService()

    async def fake_call_model(**kwargs):
        return '''{
          "has_ambiguity": true,
          "question_set": [
            {
              "question": "Metrik mana yang dimaksud?",
              "level_1_label": "Database-sourced ambiguity",
              "level_2_label": "AmbiSchema",
              "description": {
                "options": ["kpi_master_records::target", "kpi_tracker_records::realisasi"]
              }
            }
          ]
        }'''

    monkeypatch.setattr(service.llm, "call_model", fake_call_model)

    result = await service._assess_ambiguity_with_llm("KPI terbaik", "admin", "")

    assert result.answer_options == [
        "kpi_master_records::target",
        "kpi_tracker_records::realisasi",
    ]
    assert "Lewati" not in result.answer_options
    assert "Lainnya" not in result.answer_options


@pytest.mark.asyncio
async def test_detector_maps_ambisql_question_set_to_detected_ambiguities():
    """Test detector maps new question_set format to DetectedAmbiguity objects."""
    detector = AmbiguityDetectorService()

    with patch.object(detector.llm, 'call_model', new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = '''{
            "has_ambiguity": true,
            "question_set": [
                {
                    "question": "Apakah Anda ingin data per individu atau per divisi?",
                    "level_1_label": "Database-sourced ambiguity",
                    "level_2_label": "AmbiIntent",
                    "description": {
                        "options": ["Per individu", "Per divisi", "Seluruh perusahaan"]
                    }
                }
            ]
        }'''

        result = await detector._assess_ambiguity_with_llm(
            user_query="Siapa yang performa terbaik?",
            user_role="Owner",
            kpi_context="KPI context"
        )

        assert result.is_ambiguous is True
        assert result.ambiguity_type == "AmbiIntent"
        assert len(result.detected_ambiguities) == 1

        ambiguity = result.detected_ambiguities[0]
        assert ambiguity.suggested_clarifying_question == "Apakah Anda ingin data per individu atau per divisi?"
        assert ambiguity.answer_options == [
            "Per individu", "Per divisi", "Seluruh perusahaan"]
        assert ambiguity.metadata.get("is_ambiguity_level1_type_llm") is False


@pytest.mark.asyncio
async def test_detector_accepts_ambisource_question_set_items():
    detector = AmbiguityDetectorService()

    with patch.object(detector.llm, 'call_model', new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = '''{
            "has_ambiguity": true,
            "question_set": [
                {
                    "question": "Sumber interpretasi bisnis mana yang Anda maksud?",
                    "level_1_label": "LLM-sourced ambiguity",
                    "level_2_label": "AmbiSource",
                    "description": {
                        "options": ["Definisi internal KPI", "Aturan konversi eksternal"]
                    }
                }
            ]
        }'''

        result = await detector._assess_ambiguity_with_llm(
            user_query="Tampilkan data KPI berdasarkan sumber konversi",
            user_role="Owner",
            kpi_context="KPI context"
        )

    assert result.is_ambiguous is True
    assert result.ambiguity_type == "AmbiSource"
    assert result.detected_ambiguities[0].metadata.get(
        "is_ambiguity_level1_type_llm") is True




@pytest.mark.asyncio
async def test_clarification_repository_persists_answer_options_as_ordered_rows():
    """ClarificationRepository.create persists answer_options as ordered ClarificationAnswerOption rows."""
    engine, session_factory = await _make_sqlite_session()
    session_id = uuid4()
    try:
        async with session_factory() as db:
            await _create_user_and_session(db, session_id)
            repo = ClarificationRepository(db)
            question = await repo.create(
                session_id=session_id,
                ambiguity_type="AmbiSchema",
                is_ambiguity_level1_type_llm=True,
                clarifying_question="Metrik mana yang dimaksud?",
                answer_options=["Achievement %", "Realisasi", "Lewati", "Lainnya"],
            )

            options = (await db.execute(
                select(ClarificationAnswerOption)
                .where(ClarificationAnswerOption.clarification_question_id == question.clarification_question_id)
                .order_by(ClarificationAnswerOption.option_order)
            )).scalars().all()

            assert [opt.option_text for opt in options] == ["Achievement %", "Realisasi", "Lewati", "Lainnya"]
            assert [opt.option_order for opt in options] == [0, 1, 2, 3]
    finally:
        await engine.dispose()


def test_clarification_repository_preserves_text_answer():
    repo = ClarificationRepository(db=None)

    assert repo._serialize_answer("Achievement %") == "Achievement %"
    assert repo._serialize_answer("Lewati") == "Lewati"
    assert repo._serialize_answer(None) is None


@pytest.mark.asyncio
async def test_chat_message_repository_get_recent_by_session_id_returns_chronological_limited_messages():
    engine, session_factory = await _make_sqlite_session()
    session_id = uuid4()
    try:
        async with session_factory() as db:
            await _create_user_and_session(db, session_id)
            repo = ChatMessageRepository(db)
            await repo.create(session_id=session_id, message="Pesan 1", is_sender_chatbot=False)
            await repo.create(session_id=session_id, message="Pesan 2", is_sender_chatbot=True)
            await repo.create(session_id=session_id, message="Pesan 3", is_sender_chatbot=False)
            await repo.create(session_id=session_id, message="Pesan 4", is_sender_chatbot=True)
            await db.commit()

            messages = await repo.get_recent_by_session_id(session_id=session_id, limit=3)

            assert [message.message for message in messages] == ["Pesan 2", "Pesan 3", "Pesan 4"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_fallback_rewrite_skips_lewati_and_uses_lainnya():
    from utils.helper.clarificationHelpers import build_fallback_disambiguated_query

    result = build_fallback_disambiguated_query(
        original_query="Tampilkan performa terbaik",
        clarification_answers=[
            ClarificationAnswerItem(
                question_id="q1", selected_option="Lewati"),
            ClarificationAnswerItem(
                question_id="q2", selected_option="Lainnya", free_text="gunakan weighted score"),
        ],
        additional_constraints="hanya divisi aktif",
    )

    assert "Lewati" not in result
    assert "weighted score" in result
    assert "hanya divisi aktif" in result


@pytest.mark.asyncio
async def test_process_user_query_returns_all_detected_questions():
    service = ClarificationService(db=None)
    service.repo.create = AsyncMock(side_effect=[
        SimpleNamespace(clarification_question_id=f"q{index}")
        for index in range(1, 6)
    ])


    ambiguities = [
        DetectedAmbiguity(
            ambiguity_type="AmbiSchema",
            suggested_clarifying_question=f"Question {index}?",
            answer_options=["A", "B"],
        )
        for index in range(5)
    ]

    with patch.object(service.ambiguity_detector, 'detect_ambiguity', new_callable=AsyncMock) as mock_detect:
        mock_detect.return_value = AmbiguityAssessmentResult(
            is_ambiguous=True,
            ambiguity_type="AmbiSchema",
            detection_source="llm",
            detected_ambiguities=ambiguities,
        )

        result = await service.process_user_query(
            user_query="Query ambigu",
            user_role="Admin",
            session_id=SESSION_TEST_3,
        )

    assert result.questions is not None
    assert len(result.questions) == 5


def test_nl_to_sql_prompt_includes_addon_prompt_constraint():
    from template.promptTemplate import build_nl_to_sql_prompt

    prompt = build_nl_to_sql_prompt(
        user_query="Tampilkan KPI saya",
        user_id=uuid4(),
        user_role="Karyawan",
        addon_prompt="Jawab hanya untuk KPI aktif.",
    )

    assert "[KONSTRAINT CHATBOT AKTIF]" in prompt
    assert "Jawab hanya untuk KPI aktif." in prompt


def test_nl_to_sql_prompt_is_compact_but_preserves_core_rules():
    from template.promptTemplate import build_nl_to_sql_prompt

    prompt = build_nl_to_sql_prompt(
        user_query="Tampilkan KPI Sales bulan Maret",
        user_id=uuid4(),
        user_role="Karyawan",
        column_statistics="kpi_master_records.category: unique=['KPI Sales'], non_null=1, non_zero=1",
    )

    assert len(prompt) < 6000
    assert "┌" not in prompt
    assert "└" not in prompt
    assert "Hanya generate query SELECT" in prompt
    assert "GUNAKAN kpi_tracker_records" in prompt
    assert "GUNAKAN kpi_master_users" in prompt
    assert "user_id" in prompt and "BUKAN filter default" in prompt
    assert "DILARANG KERAS melakukan cast langsung ::NUMERIC" in prompt
    assert "Response" not in prompt


def test_analysis_prompt_includes_all_query_result_rows():
    from template.promptTemplate import build_analysis_prompt

    query_result = [{"row_number": index} for index in range(1, 37)]

    prompt = build_analysis_prompt(
        user_query="Tampilkan semua data",
        executed_sql="SELECT row_number FROM test;",
        query_result=query_result,
        rows_count=36,
    )

    assert '"row_number":36' in prompt
    assert "Total: 36 baris." in prompt
    assert "Data dipotong" not in prompt


def test_analysis_prompt_preserves_explicit_employee_progress_and_description_request():
    from template.promptTemplate import build_analysis_prompt

    prompt = build_analysis_prompt(
        user_query="KPI karyawan yang realisasinya sudah mencapai target atau mendekati target sampai bulan terakhir apa saja? Tolong sertakan progress dan keterangannya.",
        executed_sql="SELECT full_name, kpi_name, realisasi, target, keterangan FROM kpi_tracker_records;",
        query_result=[
            {
                "full_name": "Andi",
                "kpi_name": "Product Launch",
                "realisasi": "3",
                "target": "3",
                "keterangan": "Maintenance berjalan baik.",
            }
        ],
        rows_count=1,
    )

    assert "Jika pertanyaan menyebut \"karyawan\"" in prompt
    assert "nama karyawan" in prompt
    assert "1. [Nama KPI]" in prompt
    assert "- Progress: realisasi [nilai] dari target [nilai]" in prompt
    assert "- Keterangan: [keterangan dari data]" in prompt



def test_analysis_prompt_includes_addon_prompt_constraint():
    from template.promptTemplate import build_analysis_prompt

    prompt = build_analysis_prompt(
        user_query="Tampilkan KPI saya",
        executed_sql="SELECT 1;",
        query_result=[{"nilai": 1}],
        rows_count=1,
        addon_prompt="Gunakan nada formal.",
    )

    assert "[KONSTRAINT CHATBOT AKTIF]" in prompt
    assert "Gunakan nada formal." in prompt


def test_ambiguity_prompt_omits_empty_addon_prompt():
    from template.promptTemplate import build_ambiguity_assessment_prompt

    prompt = build_ambiguity_assessment_prompt(
        user_query="KPI terbaik?",
        user_role="Karyawan",
        kpi_context="KPI context",
        addon_prompt="",
    )

    assert "[KONSTRAINT CHATBOT AKTIF]" not in prompt


def test_scope_policy_prompt_includes_query_role_context_schema_and_addon_prompt():
    prompt = build_scope_policy_assessment_prompt(
        user_query="Tampilkan KPI saya",
        user_role="Karyawan",
        kpi_context="KPI context evidence",
        addon_prompt="Hanya jawab KPI divisi HR.",
        session_context="User sebelumnya bertanya tentang KPI HR bulan ini.",
    )

    assert "Tampilkan KPI saya" in prompt
    assert "Karyawan" in prompt
    assert "KPI context evidence" in prompt
    assert "User sebelumnya bertanya tentang KPI HR bulan ini." in prompt
    assert "[KONSTRAINT CHATBOT AKTIF]" in prompt
    assert "Hanya jawab KPI divisi HR." in prompt
    assert "users(" in prompt
    assert '"is_out_of_scope"' in prompt
    assert '"reason"' in prompt
    assert "addon_policy_violation" in prompt


def test_scope_policy_prompt_omits_empty_addon_prompt():
    prompt = build_scope_policy_assessment_prompt(
        user_query="Tampilkan KPI saya",
        user_role="Karyawan",
        kpi_context="KPI context evidence",
        addon_prompt="",
    )

    assert "[KONSTRAINT CHATBOT AKTIF]" not in prompt
    assert "Tampilkan KPI saya" in prompt
    assert '"is_out_of_scope"' in prompt


@pytest.mark.asyncio
async def test_ambiguity_detector_passes_addon_prompt_to_prompt_builder(monkeypatch):
    detector = AmbiguityDetectorService()
    captured = {}

    def fake_builder(user_query, user_role, kpi_context="", addon_prompt=None, session_context=None):
        captured["addon_prompt"] = addon_prompt
        captured["session_context"] = session_context
        return "prompt"

    monkeypatch.setattr("service.ambiguityDetectorService.build_ambiguity_assessment_prompt", fake_builder)

    with patch.object(detector.llm, 'call_model', new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = '{"has_ambiguity": false, "question_set": []}'
        await detector.detect_ambiguity(
            "KPI terbaik?",
            "Karyawan",
            "KPI context",
            addon_prompt="Gunakan constraint bot.",
        )

    assert captured["addon_prompt"] == "Gunakan constraint bot."


@pytest.mark.asyncio
async def test_clarification_service_passes_addon_prompt_to_detector(monkeypatch):
    service = ClarificationService(db=None)
    service.repo.create = AsyncMock()
    service.ambiguity_detector.detect_ambiguity = AsyncMock(return_value=AmbiguityAssessmentResult(
        is_ambiguous=False,
        ambiguity_type="none",
        detection_source="llm",
        detected_ambiguities=[],
    ))

    monkeypatch.setattr("service.clarificationService.build_context", lambda: "KPI context")

    result = await service.process_user_query(
        user_query="Tampilkan KPI saya",
        user_role="Karyawan",
        session_id=SESSION_TEST_1,
        addon_prompt="Gunakan constraint bot.",
    )

    assert result is None
    service.ambiguity_detector.detect_ambiguity.assert_awaited_once_with(
        "Tampilkan KPI saya",
        "Karyawan",
        "KPI context",
        addon_prompt="Gunakan constraint bot.",
        session_context=None,
    )


class TestKPIPrompts:
    def test_build_clarification_choice_generation_prompt_uses_question_description_and_templates(self):
        prompt = build_clarification_choice_generation_prompt(
            question="Metrik mana yang dimaksud?",
            description=[
                "kpi_tracker::achievement, persentase pencapaian KPI",
                "kpi_tracker::actual_value, nilai aktual KPI",
            ],
            templates="AmbiSchema: list each column choice clearly.",
        )

        assert "Metrik mana yang dimaksud?" in prompt
        assert "kpi_tracker::achievement" in prompt
        assert "AmbiSchema: list each column choice clearly." in prompt
        assert '"choices"' in prompt
        assert "JSON object" in prompt

    def test_ambiguity_prompt_treats_description_options_as_candidate_context(self):
        prompt = build_ambiguity_assessment_prompt(
            user_query="bagaimana perkembangan andi",
            user_role="karyawan",
            kpi_context="schema context",
        )

        assert "description.options" in prompt
        assert "candidate" in prompt.lower() or "kandidat" in prompt.lower()
        assert "final user-facing" in prompt.lower() or "final pilihan" in prompt.lower()

    def test_ambiguity_prompt_keeps_name_and_progress_ambiguities(self):
        prompt = build_ambiguity_assessment_prompt(
            user_query="bagaimana perkembangan andi",
            user_role="karyawan",
            kpi_context="schema context",
        )

        assert '"andi"         → employee name → self-resolved via full name OR email, NOT an ambiguity' in prompt
        assert '"perkembangan" → unclear metric → AmbiView' in prompt
        assert '"level_2_label": "AmbiValue"' not in prompt
        assert '"level_2_label": "AmbiView"' in prompt

    def test_ambiguity_prompt_uses_ambisql_question_set_format(self):
        prompt = build_ambiguity_assessment_prompt(
            user_query="Tampilkan pengguna berdasarkan tanggal registrasi",
            user_role="admin",
            kpi_context="Evidence: Abstain for previous AmbiIntent",
        )

        assert "question_set" in prompt
        assert "has_ambiguity" in prompt
        assert "Question :" in prompt
        assert "Schema   :" in prompt
        assert "Evidence:" in prompt
        assert "AmbiView" in prompt
        assert "AmbiSource" not in prompt
        assert "Abstain" in prompt

    def test_ambiguity_prompt_shows_valid_json_example(self):
        prompt = build_ambiguity_assessment_prompt(
            user_query="Seberapa jauh perkembangan progress kpi akmal?",
            user_role="Owner",
            kpi_context="KPI context",
        )

        assert "<boolean>" not in prompt
        assert "<string" not in prompt
        assert "true" in prompt
        assert '"question_set": [' in prompt
        assert '"options": [' in prompt

    def test_nl_to_sql_schema_uses_user_id_not_removed_nama_orang(self):
        from template.promptTemplate import DB_SCHEMA, build_nl_to_sql_prompt

        prompt = build_nl_to_sql_prompt(
            user_query="Tampilkan KPI Akmal",
            user_id=uuid4(),
            user_role="Karyawan",
        )
        combined_prompt_context = f"{DB_SCHEMA}\n{prompt}"

        assert "nama_orang" not in combined_prompt_context
        assert "user_id UUID" in DB_SCHEMA
        assert "users.id" in DB_SCHEMA
        assert "join users" in prompt.lower()

    def test_ambiguity_prompt_uses_prd_taxonomy_and_context(self):
        prompt = build_ambiguity_assessment_prompt(
            user_query="Tampilkan sales terbaik tahun lalu",
            user_role="Kepala Divisi",
            kpi_context="KPI Master dan KPI Tracker context",
        )

        assert "AmbiSchema" in prompt
        assert "AmbiValue" in prompt
        assert "AmbiView" in prompt
        assert "AmbiRef" in prompt
        assert "question_set" in prompt
        assert "KPI Master dan KPI Tracker context" in prompt

    def test_query_disambiguation_prompt_supports_batched_answers(self):
        prompt = build_query_disambiguation_prompt(
            original_query="Tampilkan sales terbaik tahun lalu",
            clarification_answers=[
                ClarificationAnswerItem(
                    question_id="q1", selected_option="Achievement %"),
                ClarificationAnswerItem(
                    question_id="q2", selected_option="Calendar Year 2025"),
            ],
            additional_constraints="hanya divisi aktif",
        )

        assert "Achievement %" in prompt
        assert "Calendar Year 2025" in prompt
        assert "hanya divisi aktif" in prompt

    def test_query_disambiguation_prompt_uses_question_refine_contract(self):
        prompt = build_query_disambiguation_prompt(
            original_query="List all novels published after 2000 that won a Booker Prize.",
            clarification_answers=[],
            additional_constraints="Only include novels published after 2010.",
        )

        assert "Absolute Preservation" in prompt
        assert "Full Integration" in prompt
        assert "Conflict Resolution" in prompt
        assert "Natural Language" in prompt
        assert "Original question:" in prompt
        assert "Additional information:" in prompt
        assert "Only include novels published after 2010." in prompt
        assert "Kembalikan **hanya** teks pertanyaan yang telah ditulis ulang." in prompt

    def test_node_merge_prompt_returns_json_array_contract(self):
        from template.promptTemplate import build_node_merge_prompt

        prompt = build_node_merge_prompt(
            old_list=[
                {"question": "Metrik terbaik mana?", "answer": "Realisasi"}],
            new_pair={"question": "'Terbaik' merujuk ke metrik apa?",
                      "answer": "Achievement %"},
        )

        assert "Merge a new question-answer pair" in prompt
        assert "old_list" in prompt
        assert "new_pair" in prompt
        assert "same or highly similar meaning" in prompt
        assert "Return ONLY the merged list as a valid JSON array" in prompt
        assert "Achievement %" in prompt


class TestPreferenceTreeService:
    @pytest.mark.asyncio
    async def test_preference_tree_builds_leaf_map_and_records_lewati(self):
        from service.preferenceTreeService import PreferenceTree, QAPair

        tree = PreferenceTree()
        tree.llm = None
        await tree.update_tree([
            QAPair(
                level1="AmbiSchema",
                level2="terbaik",
                question="'Terbaik' merujuk ke metrik apa?",
                answer="Achievement %",
            ),
            QAPair(
                level1="AmbiRef",
                level2="tahun lalu",
                question="'Tahun lalu' merujuk ke periode mana?",
                answer="Lewati",
            ),
        ])

        schema_leaf = tree.leaf_map[("AmbiSchema", "terbaik")]
        ref_leaf = tree.leaf_map[("AmbiRef", "tahun lalu")]

        assert schema_leaf.qa_list == [
            {"question": "'Terbaik' merujuk ke metrik apa?", "answer": "Achievement %"}
        ]
        assert ref_leaf.qa_list == [
            {"question": "'Tahun lalu' merujuk ke periode mana?", "answer": "Lewati"}
        ]

        serialized = tree.serialize()
        assert serialized["children"]["AmbiSchema"]["children"]["terbaik"][
            "children"]["leaf"]["qa_list"][0]["answer"] == "Achievement %"
        assert serialized["children"]["AmbiRef"]["children"]["tahun lalu"]["children"]["leaf"]["qa_list"][0]["answer"] == "Lewati"

    @pytest.mark.asyncio
    async def test_additional_information_excludes_lewati_and_appends_constraints(self):
        from service.preferenceTreeService import PreferenceTree, QAPair

        tree = PreferenceTree()
        tree.llm = None
        qa_set = [
            QAPair(
                level1="AmbiSchema",
                level2="terbaik",
                question="'Terbaik' merujuk ke metrik apa?",
                answer="Achievement %",
            ),
            QAPair(
                level1="AmbiRef",
                level2="tahun lalu",
                question="'Tahun lalu' merujuk ke periode mana?",
                answer="Lewati",
            ),
        ]

        await tree.update_tree(qa_set)
        additional_info = tree.build_additional_information()

        lines = additional_info.splitlines()
        assert "- 'Terbaik' merujuk ke metrik apa?: Achievement %" in lines
        assert all("Lewati" not in line for line in lines)

    @pytest.mark.asyncio
    async def test_node_merge_uses_llm_response_for_semantic_conflict(self):
        from service.preferenceTreeService import PreferenceTree, QAPair

        class FakeLLM:
            async def _call_llm(self, **kwargs):
                return '[{"question": "Metrik terbaik mana?", "answer": "Achievement %"}]'

        tree = PreferenceTree()
        tree.llm = FakeLLM()
        await tree.update_tree([
            QAPair(
                level1="AmbiSchema",
                level2="terbaik",
                question="Metrik terbaik mana?",
                answer="Realisasi",
            ),
            QAPair(
                level1="AmbiSchema",
                level2="terbaik",
                question="'Terbaik' merujuk ke metrik apa?",
                answer="Achievement %",
            ),
        ])

        leaf = tree.leaf_map[("AmbiSchema", "terbaik")]
        assert leaf.qa_list == [
            {"question": "Metrik terbaik mana?", "answer": "Achievement %"}
        ]

    @pytest.mark.asyncio
    async def test_node_merge_invalid_json_falls_back_to_exact_duplicate_replace(self):
        from service.preferenceTreeService import PreferenceTree, QAPair

        class BadLLM:
            async def _call_llm(self, **kwargs):
                return 'not json'

        tree = PreferenceTree()
        tree.llm = BadLLM()
        await tree.update_tree([
            QAPair(
                level1="AmbiSchema",
                level2="terbaik",
                question="Metrik terbaik mana?",
                answer="Realisasi",
            ),
            QAPair(
                level1="AmbiSchema",
                level2="terbaik",
                question="Metrik terbaik mana?",
                answer="Achievement %",
            ),
        ])

        leaf = tree.leaf_map[("AmbiSchema", "terbaik")]
        assert leaf.qa_list == [
            {"question": "Metrik terbaik mana?", "answer": "Achievement %"}
        ]

    @pytest.mark.asyncio
    async def test_handle_clarification_response_uses_all_answered_session_history(self):
        engine, session_factory = await _make_sqlite_session()
        session_id = uuid4()
        try:
            async with session_factory() as db:
                await _create_user_and_session(db, session_id)
                repo = ClarificationRepository(db)
                previous = await repo.create(
                    session_id=session_id,
                    ambiguity_type="AmbiSchema",
                    is_ambiguity_level1_type_llm=True,
                    clarifying_question="Metrik mana yang dimaksud?",
                    answer_options=["Achievement %", "Total realisasi"],
                )
                await repo.update_with_answer(
                    log_id=previous.clarification_question_id,
                    clarification_answer="Achievement %",
                )
                current = await repo.create(
                    session_id=session_id,
                    ambiguity_type="AmbiContext",
                    is_ambiguity_level1_type_llm=True,
                    clarifying_question="Periode mana yang dimaksud?",
                    answer_options=["Q1 2025", "Q2 2025"],
                )
                await db.commit()

                service = ClarificationService(db)
                captured_prompts = []

                async def fake_call_llm(**kwargs):
                    captured_prompts.append(kwargs["prompt"])
                    return "Tampilkan achievement KPI untuk Q1 2025"

                with patch.object(service.llm, "_call_llm", new_callable=AsyncMock) as mock_llm:
                    mock_llm.side_effect = fake_call_llm
                    with patch.object(
                        service.ambiguity_detector,
                        "detect_ambiguity",
                        new_callable=AsyncMock,
                    ) as mock_detect:
                        mock_detect.return_value = AmbiguityAssessmentResult(
                            is_ambiguous=False,
                            ambiguity_type="none",
                            detection_source="llm",
                            detected_ambiguities=[],
                        )

                        result = await service.handle_clarification_response(
                            session_id=session_id,
                            clarification_answers=[
                                ClarificationAnswerItem(
                                    question_id=current.clarification_question_id,
                                    selected_option="Q1 2025",
                                )
                            ],
                            user_role="Owner",
                            original_query="Tampilkan KPI",
                        )

                assert result.disambiguated_query == "Tampilkan achievement KPI untuk Q1 2025"
                assert "- Metrik mana yang dimaksud?: Achievement %" in captured_prompts[0]
                assert "- Periode mana yang dimaksud?: Q1 2025" in captured_prompts[0]
                assert result.preference_tree is not None
                tree_text = json.dumps(result.preference_tree, ensure_ascii=False)
                assert "Metrik mana yang dimaksud?" in tree_text
                assert "Periode mana yang dimaksud?" in tree_text
        finally:
            await engine.dispose()
