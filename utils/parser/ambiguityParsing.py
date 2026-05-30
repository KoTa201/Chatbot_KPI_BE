"""
service/ambiguityParsing.py
Stateless helpers for parsing and normalizing LLM ambiguity detection responses.

Extracted from ambiguityDetectorService.py and clarificationService.py as part of
the service refactor to improve cohesion and testability.
"""

import json
import logging
import re

from schema.clarificationSchema import (
    AmbiguityAssessmentResult,
    DetectedAmbiguity,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# JSON parsing
# ---------------------------------------------------------------------------


def parse_llm_json_response(response: str) -> dict:
    """
    Parse an LLM response that may contain a JSON object.

    Handles:
    - Fenced code blocks (```json ... ```)
    - Wrapper text around the JSON object
    - Plain JSON

    Raises json.JSONDecodeError for empty or unparseable input.
    """
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


# ---------------------------------------------------------------------------
# Metadata helpers
# ---------------------------------------------------------------------------


def is_llm_sourced_level_1(level_1_label: str | None) -> bool | None:
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


def extract_description_options(description) -> list[str]:
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


# ---------------------------------------------------------------------------
# Payload normalization
# ---------------------------------------------------------------------------


def normalize_ambiguity_payload(result_dict: dict) -> AmbiguityAssessmentResult:
    """
    Normalize a raw LLM JSON response into an AmbiguityAssessmentResult.

    Supports two input formats:

    1. AmbiSQL question_set format:
       {
         "has_ambiguity": bool,
         "question_set": [
           {
             "level_1_label": "LLM-sourced ambiguity",
             "level_2_label": "time_scope",
             "question": "...",
             "description": {"options": [...]}
           }
         ]
       }

    2. Legacy flattened format:
       {
         "is_ambiguous": bool,
         "ambiguity_type": "...",
         "answer_options": [...],
         "detected_ambiguities": [...]
       }
    """
    # --- Question-set path (AmbiSQL) ---
    question_set = result_dict.get("question_set")
    has_ambiguity = result_dict.get("has_ambiguity", False)

    if question_set is not None and isinstance(question_set, list):
        detected_ambiguities: list[DetectedAmbiguity] = []

        for item in question_set:
            if not isinstance(item, dict):
                continue

            level_2_label = item.get("level_2_label")
            description = item.get("description", {})
            options = extract_description_options(description)

            if not options:
                logger.warning(
                    "Skipping question_set item with no options"
                )
                continue

            level_1_label = item.get("level_1_label")
            llm_sourced = is_llm_sourced_level_1(level_1_label)

            possible_interpretations = [{"text": opt} for opt in options]

            detected_ambiguities.append(
                DetectedAmbiguity(
                    ambiguity_type=str(level_2_label),
                    possible_interpretations=possible_interpretations,
                    suggested_clarifying_question=item.get("question"),
                    answer_options=options,
                    metadata={
                        "is_ambiguity_level1_type_llm": llm_sourced,
                        "level_1_label": level_1_label,
                    },
                )
            )

        if detected_ambiguities:
            is_ambiguous = bool(has_ambiguity) and bool(detected_ambiguities)
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
            return build_non_ambiguous_result(detection_source="llm")

    # --- Legacy / flattened path ---
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


def build_non_ambiguous_result(detection_source: str = "llm_fallback") -> AmbiguityAssessmentResult:
    """
    Build a safe "not ambiguous" AmbiguityAssessmentResult.

    Used as a fallback when ambiguity detection cannot determine ambiguity
    (e.g. LLM error, empty question_set, etc.).
    """
    return AmbiguityAssessmentResult(
        is_ambiguous=False,
        ambiguity_type="none",
        possible_interpretations=[],
        suggested_clarifying_question=None,
        answer_options=[],
        detection_source=detection_source,
        detected_ambiguities=[],
    )
