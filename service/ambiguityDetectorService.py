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

from schema.clarificationSchema import AmbiguityAssessmentResult
from service.llmService import GitHubModelsService
from template.promptTemplate import build_ambiguity_assessment_prompt

logger = logging.getLogger(__name__)


class AmbiguityDetectorService:
    """Service untuk deteksi ambiguitas query pengguna menggunakan LLM."""

    def __init__(self):
        self.llm = GitHubModelsService()
        # Tie-breaking threshold: score < 0.55 = definitely not ambiguous
        # score >= 0.65 = definitely ambiguous
        # 0.55-0.65 = borderline, treated as NOT ambiguous (prefer direct answer)
        self.AMBIGUITY_THRESHOLD = 0.65
        self.TIEBREAK_LOW = 0.55
        self.TIEBREAK_HIGH = 0.65

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
            match = re.search(r"\{[\s\S]*\}", cleaned)
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

    async def detect_ambiguity(
        self, user_query: str, user_role: str
    ) -> AmbiguityAssessmentResult:
        """
        Deteksi ambiguitas query pengguna menggunakan LLM.
        
        Args:
            user_query: Pertanyaan dari pengguna
            user_role: Role pengguna (Owner, HRD, Karyawan)
        
        Returns:
            AmbiguityAssessmentResult dengan score, tipe, dan interpretasi
        """
        logger.info(f"[AmbiguityDetector] Detecting ambiguity for query: {user_query}")

        try:
            # Single-stage: langsung call LLM untuk assessment
            result = await self._assess_ambiguity_with_llm(user_query, user_role)
            
            # Apply tie-breaking rule
            if self.TIEBREAK_LOW <= result.ambiguity_score < self.TIEBREAK_HIGH:
                logger.info(
                    f"[AmbiguityDetector] Score in borderline range "
                    f"({result.ambiguity_score}), applying tie-breaking rule (treat as NOT ambiguous)"
                )
                result.is_ambiguous = False
            
            logger.info(
                f"[AmbiguityDetector] Ambiguity assessment: "
                f"score={result.ambiguity_score}, is_ambiguous={result.is_ambiguous}, "
                f"type={result.ambiguity_type}"
            )
            return result

        except Exception as e:
            logger.warning(
                f"[AmbiguityDetector] LLM call failed ({type(e).__name__}: {str(e)}), "
                f"defaulting to NOT ambiguous (safe fallback)"
            )
            # Safe fallback: treat as NOT ambiguous when LLM fails
            return AmbiguityAssessmentResult(
                ambiguity_score=0.3,
                is_ambiguous=False,
                ambiguity_type="none",
                possible_interpretations=[],
                suggested_clarifying_question=None,
                answer_options=[],
                detection_source="llm_fallback",
            )

    async def _assess_ambiguity_with_llm(
        self, user_query: str, user_role: str
    ) -> AmbiguityAssessmentResult:
        """
        Call LLM untuk menilai ambiguitas query.
        
        Args:
            user_query: Pertanyaan dari pengguna
            user_role: Role pengguna (Owner, HRD, Karyawan)
        
        Returns:
            AmbiguityAssessmentResult dengan semua field dari LLM
        """
        try:
            # Build prompt untuk LLM
            prompt = build_ambiguity_assessment_prompt(user_query, user_role)

            # Call LLM dengan temperature rendah untuk konsistensi
            response = await self.llm.call_model(
                prompt=prompt,
                temperature=0.1,  # rendah untuk keputusan yang konsisten
                max_tokens=500,
            )

            # Parse JSON response
            result_dict = self._parse_llm_json_response(response)

            # Extract fields
            ambiguity_score = float(result_dict.get("ambiguity_score", 0.0))
            is_ambiguous = ambiguity_score >= self.AMBIGUITY_THRESHOLD
            ambiguity_type = result_dict.get("ambiguity_type", "none")
            
            # Handle possible_interpretations: could be list of strings or list of dicts
            interpretations = result_dict.get("possible_interpretations", [])
            if interpretations and isinstance(interpretations[0], str):
                # Convert list of strings to list of dicts
                possible_interpretations = [
                    {"text": interp} for interp in interpretations
                ]
            else:
                possible_interpretations = interpretations or []
            
            suggested_question = result_dict.get("suggested_clarifying_question")
            # Handle both "answer_options" and "suggested_options" field names
            answer_options = result_dict.get("answer_options") or result_dict.get("suggested_options", [])

            return AmbiguityAssessmentResult(
                ambiguity_score=ambiguity_score,
                is_ambiguous=is_ambiguous,
                ambiguity_type=ambiguity_type,
                possible_interpretations=possible_interpretations,
                suggested_clarifying_question=suggested_question,
                answer_options=answer_options,
                detection_source="llm",
            )

        except json.JSONDecodeError as e:
            logger.error(
                f"[AmbiguityDetector] Failed to parse LLM response as JSON: {e}"
            )
            raise RuntimeError(f"LLM response parsing error: {e}")

        except Exception as e:
            logger.error(f"[AmbiguityDetector] LLM API error: {type(e).__name__}: {e}")
            raise RuntimeError(f"LLM API error: {e}")
