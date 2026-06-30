"""Stateless helpers for LLM request building and response parsing.

Extracted from service/llmService.py to keep the service class focused on the
request lifecycle (retries, error mapping) rather than payload/format details.
"""

import json
from dataclasses import dataclass
from typing import Any


@dataclass
class VisualizationDecision:
    is_visualize: bool
    chart_type: str | None = None


def is_reasoning_model(model: str) -> bool:
    return model.startswith(("gpt-5", "o1", "o3", "o4"))


def build_payload(
    model: str,
    prompt: str,
    temperature: float,
    max_output_tokens: int,
    stop_sequences: list[str] | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
    }
    if is_reasoning_model(model):
        # Reasoning models only accept default temperature and use
        # max_completion_tokens instead of the legacy max_tokens. Send it via
        # extra_body so older openai SDKs without the typed kwarg still forward it.
        payload["extra_body"] = {"max_completion_tokens": max_output_tokens}
    else:
        payload["temperature"] = temperature
        payload["max_tokens"] = max_output_tokens
    if stop_sequences:
        payload["stop"] = stop_sequences
    return payload


def extract_text(response_data: dict[str, Any]) -> str:
    try:
        _raise_if_error_payload(response_data)
        message_content = _extract_message_content(response_data)
        text = _normalize_content_to_text(message_content)
        if not text:
            raise ValueError("Response LLM kosong.")
        return text
    except (KeyError, IndexError) as error:
        raise ValueError(f"Format response AI tidak sesuai: {str(error)}") from error


def _raise_if_error_payload(response_data: dict[str, Any]) -> None:
    if "error" not in response_data:
        return
    error_payload = response_data.get("error") or {}
    error_message = error_payload.get("message") or "Unknown LLM error"
    raise ValueError(f"LLM error payload: {error_message}")


def _extract_message_content(response_data: dict[str, Any]) -> Any:
    choices = response_data.get("choices", [])
    if not choices:
        raise ValueError("Tidak ada choices pada response LLM.")
    message = choices[0].get("message") or {}
    return message.get("content")


def _normalize_content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str) and item.strip():
                parts.append(item.strip())
                continue
            if isinstance(item, dict):
                text_part = item.get("text")
                if isinstance(text_part, str) and text_part.strip():
                    parts.append(text_part.strip())
        return "\n".join(parts)

    return ""


def parse_visualization_decision(raw: str) -> VisualizationDecision:
    cleaned = (raw or "").strip()
    if cleaned.startswith("```"):
        lines = [line for line in cleaned.splitlines()
                 if not line.strip().startswith("```")]
        cleaned = "\n".join(lines).strip()

    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        return VisualizationDecision(is_visualize=False, chart_type=None)

    is_visualize = bool(payload.get("is_visualize", False))
    chart_type = payload.get("chart_type")
    if is_visualize and not chart_type:
        chart_type = "bar"

    return VisualizationDecision(is_visualize=is_visualize, chart_type=chart_type)


def clean_sql_output(raw: str) -> str:
    """Strip markdown fences from an LLM SQL response."""
    sql = raw.strip()
    if sql.startswith("```"):
        lines = [l for l in sql.split("\n") if not l.strip().startswith("```")]
        sql = "\n".join(lines).strip()
    return sql
