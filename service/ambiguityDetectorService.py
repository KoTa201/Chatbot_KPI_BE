"""
service/ambiguityDetectorService.py
Ambiguity detector untuk clarification question mechanism.

Implementasi: LLM-only approach (tanpa rule-based heuristics).
Alasan: Rule-based patterns tidak bekerja dengan baik untuk menangani
konteks dan edge cases yang kompleks. LLM lebih akurat dan konsisten.
"""

import logging

from schema.clarificationSchema import AmbiguityAssessmentResult
from utils.helper.parser.ambiguityParsing import (
    build_non_ambiguous_result,
    extract_description_options,
    is_llm_sourced_level_1,
    normalize_ambiguity_payload,
    parse_llm_json_response,
)
from service.llmService import LLMService
from template.promptTemplate import (
    build_ambiguity_assessment_prompt,
    build_scope_policy_assessment_prompt,
)
from configCredidential import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Type alias for shared LLM call kwargs
# ---------------------------------------------------------------------------

class AmbiguityDetectorService:
    """Service untuk deteksi ambiguitas query pengguna menggunakan LLM."""

    def __init__(self) -> None:
        self.llm: LLMService = LLMService()

    async def detect_ambiguity(
        self,
        user_query: str,
        user_role: str,
        kpi_context: str = "",
        addon_prompt: str | None = None,
        session_context: str | None = None,
    ) -> AmbiguityAssessmentResult:
        """
        Deteksi ambiguitas query pengguna menggunakan LLM.
        """
        logger.info("[AmbiguityDetector] Detecting ambiguity for query: %s", user_query)

        llm_kwargs: dict[str, str | None] = dict(
            user_query=user_query,
            user_role=user_role,
            kpi_context=kpi_context,
            addon_prompt=addon_prompt,
            session_context=session_context,
        )

        if (early := await self._run_scope_policy_check(**llm_kwargs)) is not None:
            return early

        return await self._run_ambiguity_check(**llm_kwargs)

    # -----------------------------------------------------------------------
    # Orchestration helpers
    # -----------------------------------------------------------------------

    async def _run_scope_policy_check(self, **llm_kwargs) -> AmbiguityAssessmentResult | None:
        """
        Jalankan scope/policy precheck.
        """
        has_addon_prompt = bool((llm_kwargs.get("addon_prompt") or "").strip())

        try:
            scope_result = await self._assess_scope_policy_with_llm(**llm_kwargs)
        except Exception as exc:
            return self._handle_scope_failure(exc, has_addon_prompt)

        logger.info(
            "[AmbiguityDetector] Scope/policy precheck: is_out_of_scope=%s, reason=%s",
            scope_result.get("is_out_of_scope"),
            scope_result.get("reason"),
        )
        return self._build_out_of_scope_result() if scope_result.get("is_out_of_scope") else None

    async def _run_ambiguity_check(self, **llm_kwargs) -> AmbiguityAssessmentResult:
        """
        Jalankan ambiguity assessment utama.
        """
        try:
            result = await self._assess_ambiguity_with_llm(**llm_kwargs)
        except Exception as exc:
            logger.warning(
                "[AmbiguityDetector] Ambiguity LLM call failed (%s: %s), "
                "defaulting to NOT ambiguous (safe fallback)",
                type(exc).__name__, exc,
            )
            return build_non_ambiguous_result(detection_source="llm_fallback")

        logger.info(
            "[AmbiguityDetector] Ambiguity assessment: is_ambiguous=%s, type=%s",
            result.is_ambiguous,
            result.ambiguity_type,
        )
        return result

    def _handle_scope_failure(
        self, exc: Exception, has_addon_prompt: bool
    ) -> AmbiguityAssessmentResult:
        """Tangani kegagalan scope/policy check dengan strategi yang sesuai."""
        exc_repr = f"{type(exc).__name__}: {exc}"

        if has_addon_prompt:
            logger.warning(
                "[AmbiguityDetector] Scope/policy precheck failed (%s), "
                "blocking query because addon prompt constraints could not be verified",
                exc_repr,
            )
            return self._build_out_of_scope_result()

        logger.warning(
            "[AmbiguityDetector] Scope/policy precheck failed (%s), "
            "defaulting to NOT ambiguous (safe fallback)",
            exc_repr,
        )
        return build_non_ambiguous_result(detection_source="llm_fallback")

    # -----------------------------------------------------------------------
    # LLM call wrappers
    # -----------------------------------------------------------------------

    async def _assess_scope_policy_with_llm(
        self,
        user_query: str,
        user_role: str,
        kpi_context: str = "",
        addon_prompt: str | None = None,
        session_context: str | None = None,
    ) -> dict:
        """Panggil LLM untuk menilai apakah query berada di luar scope/policy."""
        prompt = build_scope_policy_assessment_prompt(
            user_query,
            user_role,
            kpi_context,
            addon_prompt=addon_prompt,
            session_context=session_context,
        )
        response = await self.llm.call_model(
            prompt=prompt,
            temperature=0.1,
            max_tokens=200,
            model=settings.LLM_MODEL_OUT_SCOPE_CLASSIFIER,
        )
        result = parse_llm_json_response(response)
        logger.debug("[AmbiguityDetector] Scope policy result: %s", result)
        return {
            "is_out_of_scope": bool(result.get("is_out_of_scope", False)),
            "reason": result.get("reason", "allowed"),
        }

    async def _assess_ambiguity_with_llm(
        self,
        user_query: str,
        user_role: str,
        kpi_context: str = "",
        addon_prompt: str | None = None,
        session_context: str | None = None,
    ) -> AmbiguityAssessmentResult:
        """
        Panggil LLM untuk menilai ambiguitas query.
        """
        prompt = build_ambiguity_assessment_prompt(
            user_query,
            user_role,
            kpi_context,
            addon_prompt=addon_prompt,
            session_context=session_context,
        )
        response = await self.llm.call_model(
            prompt=prompt,
            temperature=0.1,
            max_tokens=500,
            model=settings.LLM_MODEL_DISAMBIGUATION,
        )
        result_dict = parse_llm_json_response(response)
        return normalize_ambiguity_payload(result_dict)

    # -----------------------------------------------------------------------
    # Factories
    # -----------------------------------------------------------------------

    @staticmethod
    def _build_out_of_scope_result() -> AmbiguityAssessmentResult:
        return AmbiguityAssessmentResult(
            is_ambiguous=True,
            is_out_of_scope=True,
            ambiguity_type="none",
            possible_interpretations=[],
            suggested_clarifying_question=None,
            answer_options=[],
            detection_source="llm_scope_policy",
            detected_ambiguities=[],
            is_ambiguous_level1_type_llm=False,
        )

    # -----------------------------------------------------------------------
    # Compatibility shims (deprecated — gunakan langsung dari ambiguityParsing)
    # -----------------------------------------------------------------------

    @staticmethod
    def _parse_llm_json_response(response: str) -> dict:
        """Deprecated: gunakan parse_llm_json_response dari ambiguityParsing."""
        return parse_llm_json_response(response)

    @staticmethod
    def _is_llm_sourced_level_1(level_1_label: str | None) -> bool | None:
        """Deprecated: gunakan is_llm_sourced_level_1 dari ambiguityParsing."""
        return is_llm_sourced_level_1(level_1_label)

    @staticmethod
    def _extract_description_options(description) -> list[str]:
        """Deprecated: gunakan extract_description_options dari ambiguityParsing."""
        return extract_description_options(description)