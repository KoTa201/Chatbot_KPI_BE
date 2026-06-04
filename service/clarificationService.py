"""
service/clarificationService.py
Orchestrator untuk seluruh clarification mechanism.
Mengkoordinasikan: ambiguity detection → question generation → response handling.
"""

import json
import logging
from typing import Optional, Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from configCredidential import get_settings
from repository.clarificationRepository import ClarificationRepository
from schema.clarificationSchema import (
    ClarificationAnswerItem,
    ClarificationMessageResponse,
    ClarificationQuestionResponse,
    ClarifyingQuestionData,
    QueryDisambiguationResult,
)
from service.ambiguityDetectorService import AmbiguityDetectorService
from utils.helper.clarificationHelpers import (
    answered_question_keys,
    build_fallback_disambiguated_query,
    build_qa_set,
    build_session_qa_set,
    effective_answer,
    filter_unanswered_ambiguities,
)
from service.llmService import LLMService
from service.preferenceTreeService import PreferenceTree
from template.promptTemplate import (
    build_clarification_choice_generation_prompt,
    build_context,
    build_query_disambiguation_prompt,
)

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
    ) -> None | dict[str, bool | str | list[Any]] | ClarificationMessageResponse:
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
        user_role: str = "karyawan",
        additional_constraints: str | None = None,
        original_query: str | None = None,
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
            str(answer.question_id) for answer in clarification_answers if str(answer.question_id) not in log_by_id]
        if missing:
            raise ValueError(
                f"Pertanyaan klarifikasi tidak ditemukan: {', '.join(missing)}")

        source_query = original_query or ""

        current_qa_set = build_qa_set(clarification_answers, log_by_id)
        session_qa_set = build_session_qa_set(logs, current_qa_set)

        preference_tree = PreferenceTree(llm=self.llm)
        await preference_tree.update_tree(session_qa_set)
        additional_information = preference_tree.build_additional_information()

        logger.info("[ClarificationService] Disambiguating query...")
        disambiguated_query = await self._disambiguate_query(
            original_query=source_query,
            clarification_answers=clarification_answers,
            additional_constraints=additional_constraints,
            additional_information=additional_information,
        )

        for answer in clarification_answers:
            await self.repo.update_with_answer(
                log_id=answer.question_id,
                clarification_answer=effective_answer(answer),
                free_text_answer=answer.free_text,
            )

        if self.db is not None:
            await self.db.commit()

        next_clarification = None
        recheck_result = await self._recheck_ambiguity_after_refinement(
            rewritten_query=disambiguated_query,
            user_role=user_role,
            preference_tree=preference_tree,
        )
        if recheck_result and recheck_result.is_ambiguous:
            recheck_result.detected_ambiguities = filter_unanswered_ambiguities(
                recheck_result.detected_ambiguities,
                answered_question_keys(session_qa_set),
            )
            if recheck_result.detected_ambiguities:
                next_clarification = await self._build_clarification_response_from_detection(
                    session_id=session_id,
                    ambiguity_result=recheck_result,
                )
                if self.db is not None:
                    await self.db.commit()

        return QueryDisambiguationResult(
            original_query=source_query,
            clarification_answers=clarification_answers,
            disambiguated_query=disambiguated_query,
            additional_constraints=additional_constraints,
            needs_more_clarification=next_clarification is not None,
            clarification_message=next_clarification,
            preference_tree=preference_tree.serialize(),
        )

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
            return build_fallback_disambiguated_query(
                original_query, clarification_answers, additional_constraints
            )

    async def _recheck_ambiguity_after_refinement(
        self,
        rewritten_query: str,
        user_role: str,
        preference_tree: PreferenceTree,
    ):
        evidence_context = (
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

    async def _build_clarification_response_from_detection(
        self,
        session_id: UUID,
        ambiguity_result,
        message_id: UUID | None = None,
    ) -> None | ClarificationMessageResponse:
        if not ambiguity_result or not ambiguity_result.is_ambiguous:
            return None

        detected = ambiguity_result.detected_ambiguities

        if ambiguity_result.is_out_of_scope:
            return ClarificationMessageResponse(
                session_id=session_id,
                message_type="out_of_scope",
                is_out_of_scope=True,  # 👈 consistent type, no more dict
            )

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

        query_message = (
            f"Terdapat beberapa pertanyaan yang ingin saya tanyakan terkait, silakan jawab pertanyaan berikut."
            f"{chr(10) + chr(10).join(f'{i + 1}. {q.question}' for i, q in enumerate(questions)) if questions else ''}"
        )

        return ClarificationMessageResponse(
            session_id=session_id,
            message_type="clarification",
            clarifying_question=query_message,
            options=questions[0].options if questions else None,
            questions=questions,
        )

    async def _generate_clarifying_question(
        self,
        ambiguity_type: str,
        suggested_question: Optional[str],
        suggested_options: Optional[list[str]],
        metadata: dict | None = None,
    ) -> ClarifyingQuestionData:
        question = suggested_question or ""
        candidate_options = suggested_options or []
        try:
            prompt = build_clarification_choice_generation_prompt(
                question=question,
                description=candidate_options,
                templates=self._choice_generation_templates(),
            )
            response = await self.llm._call_llm(
                prompt=prompt,
                temperature=0.2,
                max_output_tokens=300,
                model=settings.LLM_MODEL_DISAMBIGUATION,
            )
            options = self._normalize_generated_choices(response)
            logger.info("[ClarificationGenerator] Generated options via standalone CQ prompt")
        except Exception as exc:
            logger.warning(
                "[ClarificationGenerator] CQ generation failed (%s); using detector options fallback",
                exc,
            )
            options = self._fallback_choices(candidate_options)

        return ClarifyingQuestionData(
            clarifying_question=question,
            options=options,
            default_if_no_answer="Lewati",
            ambiguity_type=ambiguity_type,
            metadata=metadata or {},
        )

    @staticmethod
    def _choice_generation_templates() -> str:
        return """
        AmbiSchema: list every plausible column as a descriptive sentence using column_name::table_name and the column description.
        AmbiValue: list every plausible database value or WHERE interpretation with short evidence.
        AmbiView: list every plausible metric, aggregation, or SQL operation with a clear user-facing meaning.
        AmbiContext: list concrete values, ranges, or constraints the user can choose.
        AmbiFallacy: list likely corrections for the contradictory reference.
        AmbiRef: list concrete temporal or spatial interpretations.
        """.strip()

    @classmethod
    def _normalize_generated_choices(cls, response: str) -> list[str]:
        payload = json.loads(response.strip())
        raw_choices = payload.get("choices")
        if not isinstance(raw_choices, list):
            raise ValueError("CQ generation response must contain choices list")

        content_choices = [
            str(choice).strip()
            for choice in raw_choices
            if str(choice).strip() and str(choice).strip() not in {"Abstain", "Others", "Lewati", "Lainnya"}
        ]
        if not content_choices:
            raise ValueError("CQ generation returned no content choices")

        return cls._limit_content_choices(content_choices) + ["Lewati", "Lainnya"]

    @classmethod
    def _fallback_choices(cls, candidate_options: list[str]) -> list[str]:
        content_choices = [
            str(option).strip()
            for option in candidate_options
            if str(option).strip() and str(option).strip() not in {"Abstain", "Others", "Lewati", "Lainnya"}
        ]
        return cls._limit_content_choices(content_choices) + ["Lewati", "Lainnya"]

    @staticmethod
    def _limit_content_choices(content_choices: list[str]) -> list[str]:
        seen = []
        for choice in content_choices:
            if choice not in seen:
                seen.append(choice)
        return seen[:5]

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





