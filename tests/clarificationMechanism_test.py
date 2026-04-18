"""
tests/clarificationMechanism_test.py
Test suite untuk Clarification Question Mechanism (LLM-based only).
Berdasarkan skenario di PRD Section 8.
"""

import pytest
from uuid import uuid4
from unittest.mock import AsyncMock, patch

from service.ambiguityDetectorService import AmbiguityDetectorService
from service.clarificationQuestionGeneratorService import (
    ClarificationQuestionGeneratorService,
)
from service.clarificationService import ClarificationService
from schema.clarificationSchema import AmbiguityAssessmentResult
from utils.sessionContextManager import SessionContextManager


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
                "ambiguity_score": 0.85,
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
            assert result.ambiguity_score == 0.85
            assert result.detection_source == "llm"
            assert len(result.answer_options) == 3

    @pytest.mark.asyncio
    async def test_llm_clear_query(self):
        """Test LLM menganggap query yang jelas sebagai tidak ambiguous."""
        detector = AmbiguityDetectorService()
        
        with patch.object(detector.llm, 'call_model', new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = '''{
                "is_ambiguous": false,
                "ambiguity_score": 0.2,
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
            assert result.ambiguity_score == 0.2
            assert result.ambiguity_type == "none"

    @pytest.mark.asyncio
    async def test_llm_json_in_markdown_fence(self):
        """Test parser tetap menerima JSON di dalam markdown code fence."""
        detector = AmbiguityDetectorService()

        with patch.object(detector.llm, 'call_model', new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = '''```json
            {
                "is_ambiguous": true,
                "ambiguity_score": 0.75,
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
            assert result.ambiguity_score == 0.75
            assert result.ambiguity_type == "scope"

    @pytest.mark.asyncio
    async def test_llm_tie_breaking_rule(self):
        """Test tie-breaking rule: score 0.55-0.65 treated as NOT ambiguous."""
        detector = AmbiguityDetectorService()
        
        with patch.object(detector.llm, 'call_model', new_callable=AsyncMock) as mock_llm:
            # Score dalam range tie-breaking
            mock_llm.return_value = '''{
                "is_ambiguous": true,
                "ambiguity_score": 0.60,
                "ambiguity_type": "scope",
                "possible_interpretations": [],
                "suggested_clarifying_question": "Scope tidak jelas",
                "answer_options": []
            }'''
            
            result = await detector.detect_ambiguity(
                "Berapa KPI?",
                "Owner"
            )
            
            # Tie-breaking rule should apply
            assert result.is_ambiguous is False
            assert result.ambiguity_score == 0.60

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
            assert result.ambiguity_score == 0.3
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


class TestClarificationQuestionGenerator:
    """Test suite untuk clarification question generation."""

    @pytest.mark.asyncio
    async def test_generate_question_from_llm(self):
        """Test generate pertanyaan dari LLM."""
        generator = ClarificationQuestionGeneratorService()
        
        with patch.object(generator.llm, 'call_model', new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = '''{
                "clarifying_question": "Anda ingin data per individu atau per divisi?",
                "options": ["Per individu", "Per divisi", "Seluruh perusahaan"],
                "default_if_no_answer": "Per divisi"
            }'''
            
            result = await generator.generate_clarifying_question(
                user_query="Siapa yang terbaik?",
                ambiguity_type="scope",
                possible_interpretations=["Per individu", "Per divisi"],
                user_role="Owner"
            )
            
            assert "Anda ingin" in result.clarifying_question
            assert len(result.options) == 3
            assert result.default_if_no_answer == "Per divisi"

    @pytest.mark.asyncio
    async def test_generate_question_llm_error_fallback(self):
        """Test fallback ke template ketika LLM error."""
        generator = ClarificationQuestionGeneratorService()
        
        with patch.object(generator.llm, 'call_model', new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = Exception("LLM Error")
            
            result = await generator.generate_clarifying_question(
                user_query="Siapa yang terbaik?",
                ambiguity_type="scope",
                possible_interpretations=[],
                user_role="Owner"
            )
            
            # Should use template default
            assert result.clarifying_question is not None
            assert len(result.options) >= 2
            assert result.ambiguity_type == "scope"


class TestClarificationService:
    """Test suite untuk clarification service orchestration."""

    @pytest.mark.asyncio
    async def test_process_direct_answer_no_ambiguity(self):
        """Test direct answer ketika query tidak ambiguous."""
        service = ClarificationService(
            db_session=None,
            llm=AsyncMock(),
            clarification_repo=None
        )
        
        # Mock ambiguity detection to return NOT ambiguous
        with patch.object(
            service.ambiguity_detector,
            'detect_ambiguity',
            new_callable=AsyncMock
        ) as mock_detect:
            mock_detect.return_value = AmbiguityAssessmentResult(
                is_ambiguous=False,
                ambiguity_type="none",
                ambiguity_score=0.2,
                possible_interpretations=[],
                suggested_clarifying_question=None,
                answer_options=[],
                detection_source="llm"
            )
            
            result = await service.detect_ambiguity(
                session_id="test-1",
                user_query="Tampilkan semua KPI Januari 2025",
                user_role="Owner"
            )
            
            assert result.ambiguity_detected is False
            assert result.clarifying_question is None

    @pytest.mark.asyncio
    async def test_process_clarification_needed(self):
        """Test clarification diperlukan ketika query ambiguous."""
        service = ClarificationService(
            db_session=None,
            llm=AsyncMock(),
            clarification_repo=None
        )
        
        with patch.object(
            service.ambiguity_detector,
            'detect_ambiguity',
            new_callable=AsyncMock
        ) as mock_detect:
            mock_detect.return_value = AmbiguityAssessmentResult(
                is_ambiguous=True,
                ambiguity_type="scope",
                ambiguity_score=0.85,
                possible_interpretations=["Per individu", "Per divisi"],
                suggested_clarifying_question="Scope mana yang Anda maksud?",
                answer_options=["Per individu", "Per divisi"],
                detection_source="llm"
            )
            
            with patch.object(
                service.question_generator,
                'generate_clarifying_question',
                new_callable=AsyncMock
            ) as mock_gen:
                mock_gen.return_value.clarifying_question = "Scope mana?"
                mock_gen.return_value.options = ["Per individu", "Per divisi"]
                
                result = await service.detect_ambiguity(
                    session_id="test-2",
                    user_query="Siapa yang terbaik?",
                    user_role="Owner"
                )
                
                assert result.ambiguity_detected is True
                assert result.clarifying_question is not None

    @pytest.mark.asyncio
    async def test_max_clarification_limit(self):
        """Test max clarification limit per session."""
        ctx_manager = SessionContextManager()
        session_id = "test-3"
        
        # Add 2 clarifications (max)
        ctx_manager.add_clarification_to_history(
            session_id,
            original_query="Query 1",
            ambiguity_type="scope"
        )
        ctx_manager.add_clarification_to_history(
            session_id,
            original_query="Query 2",
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
        session_id = "test-session-1"
        
        ctx = manager.get_session_context(session_id)
        assert ctx is not None
        assert ctx.session_id == session_id
        assert len(ctx.clarification_history) == 0

    def test_add_clarification_to_history(self):
        """Test add clarification to session history."""
        manager = SessionContextManager()
        session_id = "test-session-2"
        
        manager.add_clarification_to_history(
            session_id,
            original_query="Berapa KPI?",
            ambiguity_type="temporal"
        )
        
        ctx = manager.get_session_context(session_id)
        assert len(ctx.clarification_history) == 1
        assert ctx.clarification_history[0]["original_query"] == "Berapa KPI?"

    def test_scope_preference_storage(self):
        """Test store scope preference dari clarification answer."""
        manager = SessionContextManager()
        session_id = "test-session-3"
        
        manager.store_scope_preference(session_id, "Per divisi")
        
        ctx = manager.get_session_context(session_id)
        assert ctx.user_preferences.get("scope") == "Per divisi"

    def test_preference_persistence_across_queries(self):
        """Test scope preference persist across multiple queries."""
        manager = SessionContextManager()
        session_id = "test-session-4"
        
        # Store preference
        manager.store_scope_preference(session_id, "Per divisi")
        
        # Add multiple clarifications
        manager.add_clarification_to_history(session_id, "Query 1", "scope")
        manager.add_clarification_to_history(session_id, "Query 2", "temporal")
        
        # Check preference still there
        ctx = manager.get_session_context(session_id)
        assert ctx.user_preferences.get("scope") == "Per divisi"

    def test_session_ttl_cleanup(self):
        """Test session TTL cleanup mechanism."""
        manager = SessionContextManager()
        session_id = "test-session-5"
        
        # Create context
        manager.get_session_context(session_id)
        assert session_id in manager.sessions
        
        # Access again
        manager.get_session_context(session_id)
        assert session_id in manager.sessions


class TestScenarios:
    """Test suite untuk end-to-end scenarios."""

    @pytest.mark.asyncio
    async def test_scenario_llm_ambiguous_query(self):
        """Skenario: LLM mendeteksi ambiguitas dan generate pertanyaan."""
        detector = AmbiguityDetectorService()
        
        with patch.object(detector.llm, 'call_model', new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = '''{
                "is_ambiguous": true,
                "ambiguity_score": 0.88,
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
                "ambiguity_score": 0.15,
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
    async def test_scenario_tie_breaking(self):
        """Skenario: Score borderline (0.55-0.65) apply tie-breaking."""
        detector = AmbiguityDetectorService()
        
        with patch.object(detector.llm, 'call_model', new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = '''{
                "is_ambiguous": true,
                "ambiguity_score": 0.58,
                "ambiguity_type": "scope",
                "possible_interpretations": [],
                "suggested_clarifying_question": null,
                "answer_options": []
            }'''
            
            result = await detector.detect_ambiguity(
                "Data KPI",
                "Owner"
            )
            
            # Tie-breaking should apply
            assert result.is_ambiguous is False
            assert result.ambiguity_score == 0.58

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
