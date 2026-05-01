"""
service/clarificationService.py
Orchestrator untuk seluruh clarification mechanism.
Mengkoordinasikan: ambiguity detection → question generation → response handling.
"""

import logging
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from schema.clarificationSchema import (
    QueryDisambiguationResult,
    ClarificationMessageResponse,
)
from service.ambiguityDetectorService import AmbiguityDetectorService
from service.clarificationQuestionGeneratorService import (
    ClarificationQuestionGeneratorService,
)
from service.llmService import LLMService
from repository.clarificationRepository import ClarificationRepository
from template.promptTemplate import build_query_disambiguation_prompt
from configCredidential import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()


class ClarificationService:
    """Orchestrator untuk clarification mechanism."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.ambiguity_detector = AmbiguityDetectorService()
        self.question_generator = ClarificationQuestionGeneratorService()
        self.llm = LLMService()
        self.repo = ClarificationRepository(db)

    async def process_user_query(
        self,
        user_query: str,
        user_id: UUID,
        user_role: str,
        session_id: str,
        clarification_count: int = 0,
    ) -> ClarificationMessageResponse | None:
        """
        Process query dan tentukan: clarify atau direct?

        Return:
        - ClarificationMessageResponse (jika perlu klarifikasi)
        - None (jika langsung menjawab, tidak perlu klarifikasi)
        """

        # STEP 1: Detect ambiguity
        ambiguity_result = await self.ambiguity_detector.detect_ambiguity(
            user_query, user_role
        )
        logger.info(
            f"[ClarificationService] Ambiguity detected: score={ambiguity_result.ambiguity_score}, "
            f"is_ambiguous={ambiguity_result.is_ambiguous}"
        )

        # STEP 2: Tentukan decision: clarify atau direct?
        # Apply max clarification limit: jangan tanya lebih dari 1x per query
        if not ambiguity_result.is_ambiguous or clarification_count >= 1:
            # Direct answer
            logger.info(
                f"[ClarificationService] Decision: DIRECT (count={clarification_count})")

            # Log keputusan ke database
            await self.repo.create(
                session_id=session_id,
                user_id=user_id,
                user_role=user_role,
                original_query=user_query,
                ambiguity_score=ambiguity_result.ambiguity_score,
                ambiguity_type=ambiguity_result.ambiguity_type,
                decision="direct",
                decision_source=ambiguity_result.detection_source,
            )

            return None  # Tidak perlu klarifikasi, lanjut ke pipeline RAG

        # STEP 3: Generate clarifying question
        logger.info("[ClarificationService] Decision: CLARIFY")
        clarifying_q = await self.question_generator.generate_clarifying_question(
            user_query=user_query,
            ambiguity_type=ambiguity_result.ambiguity_type,
            possible_interpretations=ambiguity_result.possible_interpretations,
            suggested_question=ambiguity_result.suggested_clarifying_question,
            suggested_options=ambiguity_result.answer_options,
            user_role=user_role,
        )

        # STEP 4: Log clarification request
        log = await self.repo.create(
            session_id=session_id,
            user_id=user_id,
            user_role=user_role,
            original_query=user_query,
            ambiguity_score=ambiguity_result.ambiguity_score,
            ambiguity_type=ambiguity_result.ambiguity_type,
            decision="clarify",
            decision_source=ambiguity_result.detection_source,
            clarifying_question=clarifying_q.clarifying_question,
        )
        logger.info(f"[ClarificationService] Clarification logged: {log.id}")

        # STEP 5: Return response untuk ditampilkan ke user
        return ClarificationMessageResponse(
            session_id=session_id,
            message_type="clarification",
            clarifying_question=clarifying_q.clarifying_question,
            options=clarifying_q.options,
        )

    async def handle_clarification_response(
        self,
        session_id: str,
        clarification_answer: str,
    ) -> QueryDisambiguationResult:
        """
        Handle jawaban klarifikasi dari pengguna.
        Return: query yang sudah disambiguasi.
        """
        # STEP 1: Ambil log clarification terakhir di session ini
        last_log = await self.repo.get_last_clarification(session_id)
        if not last_log:
            raise ValueError(
                f"Tidak ada pertanyaan klarifikasi untuk session {session_id}")

        original_query = last_log.original_query
        clarifying_question = last_log.clarifying_question

        if not clarifying_question:
            raise ValueError(f"Log tidak memiliki clarifying_question")

        # STEP 2: Disambiguasi query menggunakan LLM
        logger.info("[ClarificationService] Disambiguating query...")
        disambiguated_query = await self._disambiguate_query(
            original_query, clarifying_question, clarification_answer
        )

        # STEP 3: Update log dengan jawaban dan disambiguated query
        await self.repo.update_with_answer(
            log_id=last_log.id,
            clarification_answer=clarification_answer,
            disambiguated_query=disambiguated_query,
        )
        logger.info(
            f"[ClarificationService] Clarification response recorded: {last_log.id}"
        )

        # STEP 4: Return result untuk next step (pipeline RAG)
        return QueryDisambiguationResult(
            original_query=original_query,
            clarifying_question=clarifying_question,
            clarification_answer=clarification_answer,
            disambiguated_query=disambiguated_query,
        )

    async def _disambiguate_query(
        self,
        original_query: str,
        clarifying_question: str,
        clarification_answer: str,
    ) -> str:
        """
        Gunakan LLM untuk mengkombinasikan query asal + jawaban klarifikasi
        menjadi query yang lebih spesifik dan jelas.

        Dengan fallback otomatis jika LLM unavailable.
        """
        try:
            prompt = build_query_disambiguation_prompt(
                original_query, clarifying_question, clarification_answer
            )

            response = await self.llm._call_llm(
                prompt=prompt,
                temperature=0.2,
                max_output_tokens=200,
                model=settings.LLM_MODEL_DISAMBIGUATION,
            )

            # Response adalah langsung disambiguated query (bukan JSON)
            disambiguated = response.strip()
            logger.info(
                f"[ClarificationService] Disambiguated via LLM: {original_query} -> {disambiguated}"
            )
            return disambiguated

        except Exception as e:
            logger.warning(
                f"[ClarificationService] Disambiguation LLM error ({e}): "
                f"Using smart fallback strategy"
            )
            # Fallback strategy: Gunakan smart combination tanpa LLM
            return self._build_fallback_disambiguated_query(
                original_query, clarification_answer
            )

    def _build_fallback_disambiguated_query(
        self,
        original_query: str,
        clarification_answer: str,
    ) -> str:
        """
        Fallback untuk disambiguasi query ketika LLM tidak available.
        Menggunakan strategi deterministic untuk mengkombinasikan query dengan jawaban.
        """
        # Cleanup inputs
        query = original_query.strip()
        answer = clarification_answer.strip()

        # Strategy: Smart combination based on answer type
        # Detect answer characteristics
        answer_lower = answer.lower()

        # Temporal answers (bulan, tahun, periode)
        if any(x in answer_lower for x in ["bulan", "tahun", "week", "hari", "january", "februari", "maret", "april", "mei", "juni", "juli", "agustus", "september", "oktober", "november", "desember", "2025", "2024", "2026"]):
            # Temporal answer: append period ke query
            result = f"{query} untuk {answer}"
        # Scope answers (individu, divisi, keseluruhan)
        elif any(x in answer_lower for x in ["individu", "divisi", "keseluruhan", "semua", "tim", "departemen", "perusahaan"]):
            # Scope answer: specify scope
            result = f"{query} per {answer}"
        # Metric answers (persentase, nilai, jumlah)
        elif any(x in answer_lower for x in ["persentase", "nilai", "jumlah", "rata-rata", "total", "count", "sum", "average"]):
            # Metric answer: specify metric
            result = f"{query} dalam bentuk {answer}"
        # Status answers (achieve, partial, fail)
        elif any(x in answer_lower for x in ["achieve", "partial", "fail", "tercapai", "sebagian", "gagal"]):
            # Status answer: filter by status
            result = f"{query} dengan status {answer}"
        else:
            # Generic: simple combination
            result = f"{query} ({answer})"

        logger.info(
            f"[ClarificationService] Fallback disambiguated: '{query}' + '{answer}' → '{result}'"
        )
        return result

    async def get_session_clarification_history(
        self, session_id: str
    ) -> list[dict]:
        """Ambil riwayat clarification untuk satu session."""
        logs = await self.repo.get_by_session(session_id)
        return [
            {
                "question": log.clarifying_question,
                "answer": log.clarification_answer,
                "ambiguity_type": log.ambiguity_type,
                "timestamp": log.created_at.isoformat() if log.created_at else None,
            }
            for log in logs
            if log.clarifying_question  # Only clarifications, not direct answers
        ]

    async def get_clarification_count_in_session(self, session_id: str) -> int:
        """Hitung jumlah clarification dalam satu session."""
        return await self.repo.get_clarify_decisions_count(session_id)

    async def record_feedback(
        self,
        log_id: UUID,
        user_feedback: bool,
        needed_correction: bool | None = None,
    ) -> None:
        """Record feedback pengguna untuk evaluasi."""
        await self.repo.update_feedback(log_id, user_feedback, needed_correction)
        logger.info(
            f"[ClarificationService] Feedback recorded for log {log_id}")
