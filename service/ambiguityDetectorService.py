"""
service/ambiguityDetectorService.py
Ambiguity detector untuk clarification question mechanism.

Implementasi: LLM-only approach (tanpa rule-based heuristics).
Alasan: Rule-based patterns tidak bekerja dengan baik untuk menangani
konteks dan edge cases yang kompleks. LLM lebih akurat dan konsisten.
"""

import json
import logging

from schema.clarificationSchema import (
    AmbiguityAssessmentResult,
)
from utils.parser.ambiguityParsing import (
    build_non_ambiguous_result,
    extract_description_options,
    is_llm_sourced_level_1,
    normalize_ambiguity_payload,
    parse_llm_json_response,
)
from service.llmService import LLMService
from template.promptTemplate import build_ambiguity_assessment_prompt
from configCredidential import get_settings

settings = get_settings()

logger = logging.getLogger(__name__)


class AmbiguityDetectorService:
    """Service untuk deteksi ambiguitas query pengguna menggunakan LLM."""

    def __init__(self):
        self.llm = LLMService()

    async def detect_ambiguity(
        self, user_query: str,
        user_role: str,
        kpi_context: str = "",
        addon_prompt: str | None = None,
        session_context: str | None = None
    ) -> AmbiguityAssessmentResult:
        """
        Deteksi ambiguitas query pengguna menggunakan LLM.

        Args:
            user_query: Pertanyaan dari pengguna
            user_role: Role pengguna (Owner, kepala_divisi, Karyawan)
            addon_prompt: Optional addon prompt constraint

        Returns:
            AmbiguityAssessmentResult dengan score, tipe, dan interpretasi
        """
        logger.info(
            f"[AmbiguityDetector] Detecting ambiguity for query: {user_query}")

        try:
            # Single-stage: langsung call LLM untuk assessment
            result = await self._assess_ambiguity_with_llm(user_query, user_role, kpi_context, addon_prompt, session_context)

            # Check if query contains a 4-digit year (e.g. 2024, 2025, 2026)
            import re
            has_year = bool(re.search(r'\b20\d{2}\b', user_query))

            if not result.is_out_of_scope:
                # 1. Inject Year Clarification if missing
                if not has_year:
                    already_has_year = any(
                        "tahun" in (a.suggested_clarifying_question or "").lower()
                        for a in result.detected_ambiguities
                    )
                    if not already_has_year:
                        result.is_ambiguous = True
                        if result.ambiguity_type == "none" or not result.ambiguity_type:
                            result.ambiguity_type = "AmbiRef"
                        
                        from schema.clarificationSchema import DetectedAmbiguity
                        result.detected_ambiguities.append(
                            DetectedAmbiguity(
                                ambiguity_type="AmbiRef",
                                suggested_clarifying_question="Tahun data mana yang ingin Anda lihat?",
                                answer_options=[
                                    "Tahun 2025 — melihat data tahun lalu",
                                    "Tahun 2026 — melihat data tahun berjalan"
                                ]
                            )
                        )

                # 2. Inject Month Clarification if missing
                months_pattern = r'\b(januari|februari|maret|april|mei|juni|juli|agustus|september|oktober|november|desember|jan|feb|mar|apr|mei|jun|jul|ags|sep|okt|nov|des|q[1-4]|kuartal|bulan|periode|tren|history|riwayat)\b'
                has_month_or_period = bool(re.search(months_pattern, user_query.lower()))
                if not has_month_or_period:
                    already_has_month = any(
                        any(w in (a.suggested_clarifying_question or "").lower() for w in ["bulan", "periode", "kuartal"])
                        for a in result.detected_ambiguities
                    )
                    if not already_has_month:
                        result.is_ambiguous = True
                        if result.ambiguity_type == "none" or not result.ambiguity_type:
                            result.ambiguity_type = "AmbiRef"
                        
                        from schema.clarificationSchema import DetectedAmbiguity
                        result.detected_ambiguities.append(
                            DetectedAmbiguity(
                                ambiguity_type="AmbiRef",
                                suggested_clarifying_question="Periode bulan mana yang ingin Anda lihat?",
                                answer_options=[
                                    "Semua Bulan (Tren Tahunan)",
                                    "Kuartal 1 (Jan - Mar)",
                                    "Kuartal 2 (Apr - Jun)",
                                    "Kuartal 3 (Jul - Sep)",
                                    "Kuartal 4 (Okt - Des)"
                                ]
                            )
                        )

            # Check if query contains a 4-digit year (e.g. 2024, 2025, 2026)
            import re
            has_year = bool(re.search(r'\b20\d{2}\b', user_query))

            if not result.is_out_of_scope:
                # 1. Inject Year Clarification if missing
                if not has_year:
                    already_has_year = any(
                        "tahun" in (a.suggested_clarifying_question or "").lower()
                        for a in result.detected_ambiguities
                    )
                    if not already_has_year:
                        result.is_ambiguous = True
                        if result.ambiguity_type == "none" or not result.ambiguity_type:
                            result.ambiguity_type = "AmbiRef"
                        
                        from schema.clarificationSchema import DetectedAmbiguity
                        result.detected_ambiguities.append(
                            DetectedAmbiguity(
                                ambiguity_type="AmbiRef",
                                suggested_clarifying_question="Tahun data mana yang ingin Anda lihat?",
                                answer_options=[
                                    "Tahun 2025 — melihat data tahun lalu",
                                    "Tahun 2026 — melihat data tahun berjalan"
                                ]
                            )
                        )

                # 2. Inject Month Clarification if missing
                months_pattern = r'\b(januari|februari|maret|april|mei|juni|juli|agustus|september|oktober|november|desember|jan|feb|mar|apr|mei|jun|jul|ags|sep|okt|nov|des|q[1-4]|kuartal|bulan|periode|tren|history|riwayat)\b'
                has_month_or_period = bool(re.search(months_pattern, user_query.lower()))
                if not has_month_or_period:
                    already_has_month = any(
                        any(w in (a.suggested_clarifying_question or "").lower() for w in ["bulan", "periode", "kuartal"])
                        for a in result.detected_ambiguities
                    )
                    if not already_has_month:
                        result.is_ambiguous = True
                        if result.ambiguity_type == "none" or not result.ambiguity_type:
                            result.ambiguity_type = "AmbiRef"
                        
                        from schema.clarificationSchema import DetectedAmbiguity
                        result.detected_ambiguities.append(
                            DetectedAmbiguity(
                                ambiguity_type="AmbiRef",
                                suggested_clarifying_question="Periode bulan mana yang ingin Anda lihat?",
                                answer_options=[
                                    "Semua Bulan (Tren Tahunan)",
                                    "Kuartal 1 (Jan - Mar)",
                                    "Kuartal 2 (Apr - Jun)",
                                    "Kuartal 3 (Jul - Sep)",
                                    "Kuartal 4 (Okt - Des)"
                                ]
                            )
                        )

            logger.info(
                f"[AmbiguityDetector] Ambiguity assessment: "
                f"is_ambiguous={result.is_ambiguous}, type={result.ambiguity_type}"
            )
            return result

        except Exception as e:
            logger.warning(
                f"[AmbiguityDetector] LLM call failed ({type(e).__name__}: {str(e)}), "
                f"defaulting to NOT ambiguous (safe fallback)"
            )
            # Safe fallback: treat as NOT ambiguous when LLM fails
            return build_non_ambiguous_result(detection_source="llm_fallback")

    @staticmethod
    def _parse_llm_json_response(response: str) -> dict:
        """Delegates to parse_llm_json_response helper. Kept for compatibility."""
        return parse_llm_json_response(response)

    @staticmethod
    def _is_llm_sourced_level_1(level_1_label: str | None) -> bool | None:
        """Delegates to is_llm_sourced_level_1 helper. Kept for compatibility."""
        return is_llm_sourced_level_1(level_1_label)

    @staticmethod
    def _extract_description_options(description) -> list[str]:
        """Delegates to extract_description_options helper. Kept for compatibility."""
        return extract_description_options(description)

    async def _assess_ambiguity_with_llm(
        self, user_query: str, user_role: str, kpi_context: str = "", addon_prompt: str | None = None, session_context: str | None = None
    ) -> AmbiguityAssessmentResult:
        """
        Call LLM untuk menilai ambiguitas query.

        Args:
            user_query: Pertanyaan dari pengguna
            user_role: Role pengguna (Owner, kepala_divisi, Karyawan)
            addon_prompt: Optional addon prompt constraint

        Returns:
            AmbiguityAssessmentResult dengan semua field dari LLM
        """
        try:
            # Build prompt untuk LLM
            prompt = build_ambiguity_assessment_prompt(
                user_query, user_role, kpi_context, addon_prompt=addon_prompt, session_context=session_context)


            # Call LLM dengan temperature rendah untuk konsistensi
            response = await self.llm.call_model(
                prompt=prompt,
                temperature=0.1,  # rendah untuk keputusan yang konsisten
                max_tokens=500,
                model=settings.LLM_MODEL_DISAMBIGUATION,
            )

            # Parse JSON response and normalize to AmbiguityAssessmentResult
            result_dict = parse_llm_json_response(response)
            return normalize_ambiguity_payload(result_dict)

        except json.JSONDecodeError as e:
            logger.error(
                f"[AmbiguityDetector] Failed to parse LLM response as JSON: {e}"
            )
            raise RuntimeError(f"LLM response parsing error: {e}")

        except Exception as e:
            logger.warning(
                f"[AmbiguityDetector] LLM API error: {type(e).__name__}: {e}")
            raise RuntimeError(f"LLM API error: {e}")
