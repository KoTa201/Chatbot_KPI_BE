"""
service/clarificationService.py
Orchestrator untuk seluruh clarification mechanism.
Mengkoordinasikan: ambiguity detection → question generation → response handling.
"""

import json
import logging
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from schema.clarificationSchema import (
    QueryDisambiguationResult,
    ClarificationMessageResponse,
    ClarificationQuestionResponse,
    ClarificationAnswerItem,
)
from service.ambiguityDetectorService import AmbiguityDetectorService
from service.llmService import LLMService
from service.preferenceTreeService import PreferenceTree, QAPair
from repository.clarificationRepository import ClarificationRepository
from template.promptTemplate import build_query_disambiguation_prompt, build_context
from configCredidential import get_settings
from collections.abc import Mapping
from typing import Optional

from schema.clarificationSchema import ClarifyingQuestionData

logger = logging.getLogger(__name__)

settings = get_settings()


class ClarificationService:
    """Orchestrator untuk clarification mechanism."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.ambiguity_detector = AmbiguityDetectorService()
        self.llm = LLMService()
        self.repo = ClarificationRepository(db)

    async def process_user_query(
        self,
        user_query: str,
        user_role: str,
        session_id: UUID,
        addon_prompt: str | None = None,
        message_id: UUID | None = None,
    ) -> ClarificationMessageResponse | None:
        """
        Process query dan tentukan: clarify atau direct?

        Return:
        - ClarificationMessageResponse (jika perlu klarifikasi)
        - None (jika langsung menjawab, tidak perlu klarifikasi)
        """

        # STEP 1: Detect ambiguity
        kpi_context = build_context()
        ambiguity_result = await self.ambiguity_detector.detect_ambiguity(
            user_query, user_role, kpi_context, addon_prompt=addon_prompt
        )
        logger.info(
            f"[ClarificationService] Ambiguity detected: "
            f"is_ambiguous={ambiguity_result.is_ambiguous}"
        )

        if not ambiguity_result.is_ambiguous:
            await self.repo.create(
                session_id=session_id,
                ambiguity_type=ambiguity_result.ambiguity_type,
                is_ambiguity_level1_type_llm=ambiguity_result.is_ambiguous_level1_type_llm,
                clarifying_question=(ambiguity_result.suggested_clarifying_question or user_query)[:500],
                answer_options=ambiguity_result.answer_options,
                message_id=message_id,
            )
            return None

        logger.info("[ClarificationService] Decision: CLARIFY")
        return await self._build_clarification_response_from_detection(
            session_id=session_id,
            ambiguity_result=ambiguity_result,
            message_id=message_id,
        )

    async def handle_clarification_response(
        self,
        session_id: UUID,
        clarification_answers: list[ClarificationAnswerItem],
        additional_constraints: str | None = None,
        original_query: str | None = None,
        refinement_round: int = 1,
    ) -> QueryDisambiguationResult:
        """
        Handle jawaban klarifikasi dari pengguna.
        Return: query yang sudah disambiguasi.
        """
        logs = await self.repo.get_by_session(session_id)
        if not logs:
            raise ValueError(
                f"Tidak ada pertanyaan klarifikasi untuk session {session_id}")

        log_by_id = {str(log.clarification_question_id): log for log in logs}
        missing = [
            answer.question_id for answer in clarification_answers if answer.question_id not in log_by_id]
        if missing:
            raise ValueError(
                f"Pertanyaan klarifikasi tidak ditemukan: {', '.join(missing)}")

        source_query = original_query or ""
        qa_set = self._build_qa_set(clarification_answers, log_by_id)
        preference_tree = PreferenceTree(llm=self.llm)
        await preference_tree.update_tree(qa_set)
        additional_information = preference_tree.build_additional_information(
            qa_set=qa_set,
            additional_constraints=additional_constraints,
        )

        logger.info("[ClarificationService] Disambiguating query...")
        disambiguated_query = await self._disambiguate_query(
            original_query=source_query,
            clarification_answers=clarification_answers,
            additional_constraints=additional_constraints,
            additional_information=additional_information,
        )

        for answer in clarification_answers:
            effective_answer = answer.free_text if answer.selected_option == "Lainnya" and answer.free_text else answer.selected_option
            await self.repo.update_with_answer(
                log_id=answer.question_id,
                clarification_answer=effective_answer,
                free_text_answer=answer.free_text,
            )

        await self.db.commit()

        recheck_result = await self._recheck_ambiguity_after_refinement(
            rewritten_query=disambiguated_query,
            user_role="User",
            preference_tree=preference_tree,
            refinement_round=refinement_round,
        )
        next_clarification = None
        if recheck_result and recheck_result.is_ambiguous and refinement_round < 3:
            answered_questions = {pair.question.strip().casefold() for pair in qa_set}
            recheck_result.detected_ambiguities = [
                ambiguity
                for ambiguity in recheck_result.detected_ambiguities
                if (ambiguity.suggested_clarifying_question or "").strip().casefold()
                not in answered_questions
            ]
            if recheck_result.detected_ambiguities:
                next_clarification = await self._build_clarification_response_from_detection(
                    session_id=session_id,
                    ambiguity_result=recheck_result,
                )
                await self.db.commit()

        return QueryDisambiguationResult(
            original_query=source_query,
            clarification_answers=clarification_answers,
            disambiguated_query=disambiguated_query,
            additional_constraints=additional_constraints,
            needs_more_clarification=next_clarification is not None,
            clarification_message=next_clarification,
            preference_tree=preference_tree.serialize(),
            refinement_round=refinement_round,
        )

    @staticmethod
    def _build_qa_set(
        clarification_answers: list[ClarificationAnswerItem],
        log_by_id: Mapping[str, object],
    ) -> list[QAPair]:
        qa_set: list[QAPair] = []
        for answer in clarification_answers:
            log = log_by_id[answer.question_id]
            effective_answer = answer.free_text if answer.selected_option == "Lainnya" and answer.free_text else answer.selected_option
            qa_set.append(
                QAPair(
                    level1=getattr(log, "ambiguity_type", None) or "unknown",
                    level2=getattr(log, "clarification_question", None) or answer.question_id,
                    question=getattr(log, "clarification_question",
                                     None) or answer.question_id,
                    answer=effective_answer,
                )
            )
        return qa_set

    async def _disambiguate_query(
        self,
        original_query: str,
        clarification_answers: list[ClarificationAnswerItem],
        additional_constraints: str | None = None,
        additional_information: str | None = None,
    ) -> str:
        """
        Gunakan LLM untuk mengkombinasikan query asal + jawaban klarifikasi
        menjadi query yang lebih spesifik dan jelas.

        Dengan fallback otomatis jika LLM unavailable.
        """
        try:
            prompt = build_query_disambiguation_prompt(
                original_query=original_query,
                clarification_answers=clarification_answers,
                additional_constraints=additional_constraints,
                additional_information=additional_information,
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
                original_query, clarification_answers, additional_constraints
            )

    async def _recheck_ambiguity_after_refinement(
        self,
        rewritten_query: str,
        user_role: str,
        preference_tree: PreferenceTree,
        refinement_round: int,
    ):
        evidence_context = (
            f"Refinement round: {refinement_round}\n"
            f"Serialized preference tree: {json.dumps(preference_tree.serialize(), ensure_ascii=False)}"
        )
        try:
            return await self.ambiguity_detector.detect_ambiguity(
                rewritten_query,
                user_role,
                evidence_context,
            )
        except Exception as exc:
            logger.warning(
                "[ClarificationService] Ambiguity re-check failed: %s", exc)
            return None

    @staticmethod
    def _build_fallback_disambiguated_query(
            original_query: str,
        clarification_answers: list[ClarificationAnswerItem],
        additional_constraints: str | None = None,
    ) -> str:
        """
        Fallback untuk disambiguasi query ketika LLM tidak available.
        Menggunakan strategi deterministic untuk mengkombinasikan query dengan jawaban.
        """
        query = original_query.strip()
        additions: list[str] = []
        for answer in clarification_answers:
            if answer.selected_option == "Lewati":
                continue
            if answer.selected_option == "Lainnya" and answer.free_text:
                additions.append(answer.free_text.strip())
            else:
                additions.append(answer.selected_option.strip())
        if additional_constraints:
            additions.append(additional_constraints.strip())
        if not additions:
            return query
        return f"{query} ({'; '.join(additions)})"

    async def _build_clarification_response_from_detection(
        self,
        session_id: UUID,
        ambiguity_result,
        message_id: UUID| None = None,
    ) -> ClarificationMessageResponse | None:
        if not ambiguity_result or not ambiguity_result.is_ambiguous:
            return None

        detected = ambiguity_result.detected_ambiguities
        if not detected:
            return None

        questions: list[ClarificationQuestionResponse] = []
        for ambiguity in detected:
            clarifying_q = await self._generate_clarifying_question(
                ambiguity_type=ambiguity.ambiguity_type,
                suggested_question=ambiguity.suggested_clarifying_question,
                suggested_options=ambiguity.answer_options,
                metadata=ambiguity.metadata,
            )
            log = await self.repo.create(
                session_id=session_id,
                ambiguity_type=ambiguity.ambiguity_type,
                is_ambiguity_level1_type_llm=ambiguity.metadata.get(
                    "is_ambiguity_level1_type_llm"),
                clarifying_question=clarifying_q.clarifying_question,
                answer_options=clarifying_q.options,
                message_id=message_id,
            )
            questions.append(
                ClarificationQuestionResponse(
                    id=str(log.clarification_question_id),
                    ambiguity_type=clarifying_q.ambiguity_type or ambiguity.ambiguity_type,
                    question=clarifying_q.clarifying_question,
                    options=clarifying_q.options,
                    metadata=getattr(clarifying_q, "metadata", {}),
                )
            )

        return ClarificationMessageResponse(
            session_id=session_id,
            message_type="clarification",
            clarifying_question=questions[0].question if questions else None,
            options=questions[0].options if questions else None,
            questions=questions,
        )

    @staticmethod
    async def _generate_clarifying_question(
            ambiguity_type: str,
        suggested_question: Optional[str],
        suggested_options: Optional[list[str]],
        metadata: dict | None = None,
    ) -> ClarifyingQuestionData:
        if suggested_question and suggested_options:
            logger.info(
                "[ClarificationGenerator] Formatting detector question")
            default_options = ["Lewati", "Lainnya"]
            raw_options = [
                option for option in suggested_options if option not in default_options]
            options = raw_options[:5] + default_options
            return ClarifyingQuestionData(
                clarifying_question=suggested_question,
                options=options,
                default_if_no_answer="Lewati",
                ambiguity_type=ambiguity_type,
                metadata=metadata or {},
            )

        logger.warning(
            "[ClarificationGenerator] Detector did not provide a complete clarification question"
        )
        return ClarifyingQuestionData(
            clarifying_question="",
            options=["Lewati", "Lainnya"],
            default_if_no_answer="Lewati",
            ambiguity_type=ambiguity_type,
            metadata=metadata or {},
        )

    async def get_session_clarification_history(
        self, session_id: UUID
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

