"""
service/ambiguityDetectorService.py
Ambiguity detector untuk clarification question mechanism.

Implementasi: LLM-only approach (tanpa rule-based heuristics).
Alasan: Rule-based patterns tidak bekerja dengan baik untuk menangani
konteks dan edge cases yang kompleks. LLM lebih akurat dan konsisten.
"""

import json
import logging
import re

from schema.clarificationSchema import (
    AmbiguityAssessmentResult,
    DetectedAmbiguity,
    PRD_AMBIGUITY_TYPES,
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
        self, user_query: str, user_role: str, kpi_context: str = "", addon_prompt: str | None = None
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
            result = await self._assess_ambiguity_with_llm(user_query, user_role, kpi_context, addon_prompt)

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
            return AmbiguityAssessmentResult(
                is_ambiguous=False,
                ambiguity_type="none",
                possible_interpretations=[],
                suggested_clarifying_question=None,
                answer_options=[],
                detection_source="llm_fallback",
                detected_ambiguities=[],
            )

    @staticmethod
    def _parse_llm_json_response(response: str) -> dict:
        cleaned = (response or "").strip()
        if not cleaned:
            raise json.JSONDecodeError("Empty response", response or "", 0)

        # Support fenced output (```json ... ```) and extra wrapper text.
        if cleaned.startswith("```"):
            cleaned = re.sub(
                r"^```(?:json)?\s*|\s*```$",
                "",
                cleaned,
                flags=re.IGNORECASE | re.DOTALL,
            ).strip()

        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r"\{[\s\S]*}", cleaned)
            if not match:
                raise
            parsed = json.loads(match.group(0))

        if not isinstance(parsed, dict):
            raise json.JSONDecodeError(
                "JSON root must be object",
                cleaned,
                0,
            )
        return parsed

    @staticmethod
    def _is_llm_sourced_level_1(level_1_label: str | None) -> bool | None:
        """
        Map level_1_label to boolean indicating if ambiguity is LLM-sourced.

        Returns:
            True if "LLM-sourced ambiguity"
            False if "Database-sourced ambiguity"
            None otherwise
        """
        if not level_1_label:
            return None
        label_lower = level_1_label.lower()
        if "llm-sourced" in label_lower or "llm sourced" in label_lower:
            return True
        if "database-sourced" in label_lower or "database sourced" in label_lower:
            return False
        return None

    @staticmethod
    def _extract_description_options(description) -> list[str]:
        """
        Extract options from the description field.

        Args:
            description: Can be dict with "options" key, or other types

        Returns:
            List of option strings, or empty list if not extractable
        """
        if isinstance(description, dict) and "options" in description:
            options = description["options"]
            if isinstance(options, list):
                return [str(opt) for opt in options]
        return []

    async def _assess_ambiguity_with_llm(
        self, user_query: str, user_role: str, kpi_context: str = "", addon_prompt: str | None = None
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
                user_query, user_role, kpi_context, addon_prompt=addon_prompt)

            # Call LLM dengan temperature rendah untuk konsistensi
            response = await self.llm.call_model(
                prompt=prompt,
                temperature=0.1,  # rendah untuk keputusan yang konsisten
                max_tokens=500,
                model=settings.LLM_MODEL_DISAMBIGUATION,
            )

            # Parse JSON response
            result_dict = self._parse_llm_json_response(response)

            # NEW: Parse question_set format (AmbiSQL strict JSON output)
            question_set = result_dict.get("question_set")
            has_ambiguity = result_dict.get("has_ambiguity", False)

            if question_set is not None and isinstance(question_set, list):
                detected_ambiguities = []

                for item in question_set:
                    if not isinstance(item, dict):
                        continue

                    level_2_label = item.get("level_2_label")

                    # Extract options from description
                    description = item.get("description", {})
                    options = self._extract_description_options(description)

                    if not options:
                        logger.warning(
                            f"[AmbiguityDetector] Skipping question_set item with no options"
                        )
                        continue

                    # Determine if LLM-sourced or database-sourced
                    level_1_label = item.get("level_1_label")
                    is_llm_sourced = self._is_llm_sourced_level_1(
                        level_1_label)

                    # Build possible_interpretations from options
                    possible_interpretations = [
                        {"text": opt} for opt in options]

                    # Create DetectedAmbiguity
                    detected_ambiguities.append(
                        DetectedAmbiguity(
                            ambiguity_type=str(level_2_label),
                            possible_interpretations=possible_interpretations,
                            suggested_clarifying_question=item.get("question"),
                            answer_options=options,  # Raw options, no normalization here
                            metadata={
                                "is_ambiguity_level1_type_llm": is_llm_sourced,
                                "level_1_label": level_1_label,
                            },
                        )
                    )

                # If we have valid question_set items, return result
                if detected_ambiguities:
                    is_ambiguous = bool(has_ambiguity) and bool(
                        detected_ambiguities)
                    primary = detected_ambiguities[0]

                    return AmbiguityAssessmentResult(
                        is_ambiguous=is_ambiguous,
                        ambiguity_type=primary.ambiguity_type,
                        possible_interpretations=primary.possible_interpretations,
                        suggested_clarifying_question=primary.suggested_clarifying_question,
                        answer_options=primary.answer_options,
                        detection_source="llm",
                        detected_ambiguities=detected_ambiguities,
                        is_ambiguous_level1_type_llm=primary.metadata.get(
                            "is_ambiguity_level1_type_llm"),
                    )
                else:
                    # No valid items in question_set, return not ambiguous
                    return AmbiguityAssessmentResult(
                        is_ambiguous=False,
                        ambiguity_type="none",
                        possible_interpretations=[],
                        suggested_clarifying_question=None,
                        answer_options=[],
                        detection_source="llm",
                        detected_ambiguities=[],
                    )

            detected_items = result_dict.get("detected_ambiguities", []) or []
            detected_ambiguities = [
                DetectedAmbiguity(
                    ambiguity_type=item.get("ambiguity_type", "none"),
                    possible_interpretations=item.get("possible_interpretations", []) or [],
                    suggested_clarifying_question=item.get("suggested_clarifying_question"),
                    answer_options=item.get("answer_options") or item.get("suggested_options", []) or [],
                    metadata=item.get("metadata", {}) or {},
                )
                for item in detected_items
                if isinstance(item, dict)
            ]

            if not detected_ambiguities:
                interpretations = result_dict.get("possible_interpretations", [])
                if interpretations and isinstance(interpretations[0], str):
                    possible_interpretations = [{"text": interp} for interp in interpretations]
                else:
                    possible_interpretations = interpretations or []
                if result_dict.get("ambiguity_type", "none") != "none":
                    detected_ambiguities = [
                        DetectedAmbiguity(
                            ambiguity_type=result_dict.get("ambiguity_type", "none"),
                            possible_interpretations=possible_interpretations,
                            suggested_clarifying_question=result_dict.get("suggested_clarifying_question"),
                            answer_options=result_dict.get("answer_options") or result_dict.get("suggested_options", []) or [],
                        )
                    ]

            is_ambiguous = bool(result_dict.get("is_ambiguous", bool(detected_ambiguities))) and bool(
                detected_ambiguities or result_dict.get("answer_options"))
            primary = detected_ambiguities[0] if detected_ambiguities else None

            return AmbiguityAssessmentResult(
                is_ambiguous=is_ambiguous,
                ambiguity_type=primary.ambiguity_type if primary else result_dict.get("ambiguity_type", "none"),
                possible_interpretations=primary.possible_interpretations if primary else result_dict.get("possible_interpretations", []) or [],
                suggested_clarifying_question=primary.suggested_clarifying_question if primary else result_dict.get("suggested_clarifying_question"),
                answer_options=primary.answer_options if primary else result_dict.get("answer_options", []) or [],
                detection_source="llm",
                detected_ambiguities=detected_ambiguities,
            )

        except json.JSONDecodeError as e:
            logger.error(
                f"[AmbiguityDetector] Failed to parse LLM response as JSON: {e}"
            )
            raise RuntimeError(f"LLM response parsing error: {e}")

        except Exception as e:
            logger.error(
                f"[AmbiguityDetector] LLM API error: {type(e).__name__}: {e}")
            raise RuntimeError(f"LLM API error: {e}")
