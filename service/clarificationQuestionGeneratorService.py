"""
service/clarificationQuestionGeneratorService.py
Generator untuk pertanyaan klarifikasi yang spesifik dan actionable.
"""

import json
import logging
from typing import Optional

from schema.clarificationSchema import ClarifyingQuestionData
from service.llmService import LLMService
from template.promptTemplate import build_clarifying_question_prompt
from configCredidential import get_settings

settings = get_settings()

logger = logging.getLogger(__name__)


class ClarificationQuestionGeneratorService:
    """Service untuk generate pertanyaan klarifikasi yang tepat sasaran."""

    def __init__(self):
        self.llm = LLMService()

    async def generate_clarifying_question(
        self,
        user_query: str,
        ambiguity_type: str,
        possible_interpretations: list[dict],
        suggested_question: Optional[str],
        suggested_options: Optional[list[str]],
        user_role: str,
    ) -> ClarifyingQuestionData:
        """
        Generate pertanyaan klarifikasi yang spesifik.

        Jika suggested_question sudah ada (dari rule-based), gunakan itu.
        Jika tidak, panggil LLM untuk generate.
        """
        # Jika sudah ada saran dari rule-based, gunakan itu
        if suggested_question and suggested_options:
            logger.info("[ClarificationGenerator] Using rule-based suggestion")
            return ClarifyingQuestionData(
                clarifying_question=suggested_question,
                options=suggested_options,
                default_if_no_answer=self._get_default_answer(
                    ambiguity_type, suggested_options
                ),
                ambiguity_type=ambiguity_type,
            )

        # Fallback: panggil LLM untuk generate
        logger.info("[ClarificationGenerator] Generating via LLM")
        return await self._generate_via_llm(
            user_query, ambiguity_type, possible_interpretations, user_role
        )

    async def _generate_via_llm(
        self,
        user_query: str,
        ambiguity_type: str,
        possible_interpretations: list[dict],
        user_role: str,
    ) -> ClarifyingQuestionData:
        """Panggil LLM untuk generate pertanyaan klarifikasi."""
        try:
            prompt = build_clarifying_question_prompt(
                user_query,
                ambiguity_type,
                possible_interpretations,
                user_role,
            )

            response = await self.llm.call_model(
                prompt=prompt,
                temperature=0.3,
                max_tokens=300,
                model=settings.LLM_MODEL_DISAMBIGUATION,
            )

            # Parse JSON response
            result_dict = json.loads(response)

            options = result_dict.get("options", [])
            # Validate: harus 2-4 opsi
            if len(options) < 2:
                logger.warning(
                    f"[ClarificationGenerator] LLM returned < 2 options, using default fallback"
                )
                return self._get_default_clarification(ambiguity_type, user_query)

            return ClarifyingQuestionData(
                clarifying_question=result_dict.get("clarifying_question", ""),
                options=options,
                default_if_no_answer=result_dict.get(
                    "default_if_no_answer", options[0]
                ),
                ambiguity_type=ambiguity_type,
            )

        except json.JSONDecodeError as e:
            logger.warning(
                f"[ClarificationGenerator] Failed to parse LLM response: {e} - "
                f"Using default clarification for {ambiguity_type}"
            )
            return self._get_default_clarification(ambiguity_type, user_query)
        except Exception as e:
            logger.warning(
                f"[ClarificationGenerator] LLM API error: {e} - "
                f"Using default clarification for {ambiguity_type}"
            )
            return self._get_default_clarification(ambiguity_type, user_query)

    def _get_default_clarification(
        self, ambiguity_type: str, user_query: str
    ) -> ClarifyingQuestionData:
        """Fallback: generic clarification jika LLM gagal."""
        defaults = {
            "temporal": {
                "question": "Berapa periode waktu yang ingin Anda lihat?",
                "options": ["Bulan ini", "Bulan lalu", "Tahun ini", "Tahun lalu"],
                "default": "Bulan ini",
            },
            "scope": {
                "question": "Anda ingin melihat data dari ruang lingkup mana?",
                "options": ["Per individu", "Per divisi", "Seluruh perusahaan"],
                "default": "Per divisi",
            },
            "aggregation": {
                "question": "Bagaimana Anda ingin data dirangkum?",
                "options": ["Total", "Rata-rata", "Per individu"],
                "default": "Per individu",
            },
            "metric": {
                "question": "Metrik apa yang ingin Anda lihat?",
                "options": ["Nilai realisasi", "Persentase pencapaian", "Jumlah KPI"],
                "default": "Persentase pencapaian",
            },
            "referential": {
                "question": "Referensi siapa/apa yang Anda maksud?",
                "options": ["Saya sendiri", "Tim/divisi saya", "Seluruh organisasi"],
                "default": "Saya sendiri",
            },
        }

        fallback = defaults.get(
            ambiguity_type,
            {
                "question": "Bisakah Anda memberikan lebih banyak detail?",
                "options": ["Ya, jelaskan", "Tidak, gunakan default"],
                "default": "Gunakan default",
            },
        )

        return ClarifyingQuestionData(
            clarifying_question=fallback["question"],
            options=fallback["options"],
            default_if_no_answer=fallback["default"],
            ambiguity_type=ambiguity_type,
        )

    def _get_default_answer(
        self, ambiguity_type: str, options: list[str]
    ) -> str:
        """Tentukan default answer jika pengguna tidak menjawab."""
        defaults = {
            "temporal": "Bulan ini",
            "scope": "Per divisi",
            "aggregation": "Per individu",
            "metric": "Persentase pencapaian",
            "referential": "Saya sendiri",
        }
        default = defaults.get(ambiguity_type, options[0] if options else "")
        # Jika default tidak di dalam options, gunakan opsi pertama
        if default not in options:
            default = options[0] if options else ""
        return default
