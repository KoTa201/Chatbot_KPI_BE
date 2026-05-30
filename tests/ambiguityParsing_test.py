import json

import pytest

from utils.parser.ambiguityParsing import (
    build_non_ambiguous_result,
    normalize_ambiguity_payload,
    parse_llm_json_response,
)


def test_parse_llm_json_response_handles_fenced_json():
    payload = {"has_ambiguity": False, "question_set": []}
    response = f"```json\n{json.dumps(payload)}\n```"

    assert parse_llm_json_response(response) == payload


def test_parse_llm_json_response_handles_wrapper_text():
    response = 'Here is JSON: {"is_ambiguous": true, "answer_options": ["A"]}'

    assert parse_llm_json_response(response) == {
        "is_ambiguous": True,
        "answer_options": ["A"],
    }


def test_parse_llm_json_response_rejects_empty_response():
    with pytest.raises(json.JSONDecodeError):
        parse_llm_json_response("")


def test_normalize_ambiguity_payload_handles_question_set():
    result = normalize_ambiguity_payload(
        {
            "has_ambiguity": True,
            "question_set": [
                {
                    "level_1_label": "LLM-sourced ambiguity",
                    "level_2_label": "time_scope",
                    "question": "Periode mana yang dimaksud?",
                    "description": {"options": ["2024", "2025"]},
                }
            ],
        }
    )

    assert result.is_ambiguous is True
    assert result.ambiguity_type == "time_scope"
    assert result.answer_options == ["2024", "2025"]
    assert len(result.detected_ambiguities) == 1
    assert result.detected_ambiguities[0].metadata["is_ambiguity_level1_type_llm"] is True


def test_normalize_ambiguity_payload_handles_legacy_payload():
    result = normalize_ambiguity_payload(
        {
            "is_ambiguous": True,
            "detected_ambiguities": [
                {
                    "ambiguity_type": "metric_scope",
                    "possible_interpretations": [{"text": "Revenue"}],
                    "suggested_clarifying_question": "KPI mana?",
                    "answer_options": ["Revenue", "Cost"],
                }
            ],
        }
    )

    assert result.is_ambiguous is True
    assert result.ambiguity_type == "metric_scope"
    assert result.suggested_clarifying_question == "KPI mana?"
    assert result.answer_options == ["Revenue", "Cost"]


def test_build_non_ambiguous_result_returns_safe_fallback():
    result = build_non_ambiguous_result(detection_source="llm_fallback")

    assert result.is_ambiguous is False
    assert result.ambiguity_type == "none"
    assert result.possible_interpretations == []
    assert result.answer_options == []
    assert result.detected_ambiguities == []
    assert result.detection_source == "llm_fallback"
