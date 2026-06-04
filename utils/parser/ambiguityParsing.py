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


# ── helpers ──────────────────────────────────────────────────────────────────

def _to_interpretations(options: list[str]) -> list[dict]:
    return [{"text": opt} for opt in options]


def _coalesce_options(d: dict, *keys: str) -> list:
    for key in keys:
        val = d.get(key)
        if val:
            return val
    return []


def _build_detected(item: dict) -> DetectedAmbiguity:
    return DetectedAmbiguity(
        ambiguity_type=item.get("ambiguity_type", "none"),
        possible_interpretations=item.get("possible_interpretations") or [],
        suggested_clarifying_question=item.get("suggested_clarifying_question"),
        answer_options=_coalesce_options(item, "answer_options", "suggested_options"),
        metadata=item.get("metadata") or {},
    )


def _primary_result(
    detected: list[DetectedAmbiguity],
    is_ambiguous: bool,
    detection_source: str = "llm",
    **extra,
) -> AmbiguityAssessmentResult:
    """Build an AmbiguityAssessmentResult using the first item as the primary."""
    primary = detected[0]
    return AmbiguityAssessmentResult(
        is_ambiguous=is_ambiguous,
        ambiguity_type=primary.ambiguity_type,
        possible_interpretations=primary.possible_interpretations,
        suggested_clarifying_question=primary.suggested_clarifying_question,
        answer_options=primary.answer_options,
        detection_source=detection_source,
        detected_ambiguities=detected,
        **extra,
    )


# ── format-specific normalizers ──────────────────────────────────────────────

def _normalize_question_set(result_dict: dict) -> AmbiguityAssessmentResult:
    has_ambiguity: bool = bool(result_dict.get("has_ambiguity", False))
    detected: list[DetectedAmbiguity] = []

    for item in result_dict["question_set"]:
        if not isinstance(item, dict):
            continue

        options = extract_description_options(item.get("description", {}))
        if not options:
            logger.warning("Skipping question_set item with no options: %s", item)
            continue

        level_1_label = item.get("level_1_label")
        llm_sourced = is_llm_sourced_level_1(level_1_label)

        detected.append(
            DetectedAmbiguity(
                ambiguity_type=str(item.get("level_2_label")),
                possible_interpretations=_to_interpretations(options),
                suggested_clarifying_question=item.get("question"),
                answer_options=options,
                metadata={
                    "is_ambiguity_level1_type_llm": llm_sourced,
                    "level_1_label": level_1_label,
                },
            )
        )

    if not detected:
        return build_non_ambiguous_result(detection_source="llm")

    if has_ambiguity != bool(detected):
        logger.warning(
            "has_ambiguity=%s conflicts with %d detected items; trusting detected items",
            has_ambiguity, len(detected),
        )

    primary_meta = detected[0].metadata
    return _primary_result(
        detected,
        is_ambiguous=has_ambiguity and bool(detected),
        is_out_of_scope=primary_meta.get("is_out_of_scope", False),
        is_ambiguous_level1_type_llm=primary_meta.get("is_ambiguity_level1_type_llm"),
    )


def _normalize_legacy(result_dict: dict) -> AmbiguityAssessmentResult:
    detected: list[DetectedAmbiguity] = [
        _build_detected(item)
        for item in (result_dict.get("detected_ambiguities") or [])
        if isinstance(item, dict)
    ]

    # Fall back to top-level fields when detected_ambiguities is absent
    if not detected and result_dict.get("ambiguity_type", "none") != "none":
        raw_interps = result_dict.get("possible_interpretations") or []
        interpretations = (
            [{"text": i} for i in raw_interps]
            if raw_interps and isinstance(raw_interps[0], str)
            else raw_interps
        )
        detected = [
            DetectedAmbiguity(
                ambiguity_type=result_dict["ambiguity_type"],
                possible_interpretations=interpretations,
                suggested_clarifying_question=result_dict.get("suggested_clarifying_question"),
                answer_options=_coalesce_options(result_dict, "answer_options", "suggested_options"),
            )
        ]

    has_options = bool(detected and detected[0].answer_options) or bool(
        result_dict.get("answer_options")
    )
    is_ambiguous = bool(result_dict.get("is_ambiguous", bool(detected))) and has_options

    if not detected:
        return AmbiguityAssessmentResult(
            is_ambiguous=False,
            is_out_of_scope=result_dict.get("is_out_of_scope", False),
            ambiguity_type=result_dict.get("ambiguity_type", "none"),
            possible_interpretations=result_dict.get("possible_interpretations") or [],
            suggested_clarifying_question=result_dict.get("suggested_clarifying_question"),
            answer_options=result_dict.get("answer_options") or [],
            detection_source="llm",
            detected_ambiguities=[],
        )

    return _primary_result(detected, is_ambiguous=is_ambiguous)


# ── public entry point ────────────────────────────────────────────────────────

def normalize_ambiguity_payload(result_dict: dict) -> AmbiguityAssessmentResult:
    """
    Normalize a raw LLM JSON response into an AmbiguityAssessmentResult.

    Dispatches to one of two format-specific handlers:

    • AmbiSQL  – ``result_dict`` contains a ``"question_set"`` list.
    • Legacy   – flat structure with ``"is_ambiguous"`` / ``"detected_ambiguities"``.
    """
    if isinstance(result_dict.get("question_set"), list):
        return _normalize_question_set(result_dict)
    return _normalize_legacy(result_dict)


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
