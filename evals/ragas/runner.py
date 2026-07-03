from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4
import re
import pandas as pd
import yaml
from ragas.llms import llm_factory
from ragas.metrics import (
    AnswerCorrectness,
    AnswerRelevancy,
    AnswerSimilarity,
    ContextPrecision,
    ContextRecall,
    Faithfulness,
)
from ragas.embeddings import LangchainEmbeddingsWrapper



PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


METRIC_NAMES = [
    "answer_correctness",
    "answer_relevancy",
    "faithfulness",
    "context_recall",
    "context_precision",
]

DEFAULT_RAGAS_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_RAGAS_JUDGE_MODEL = "gpt-3.5-turbo-16k"
DEFAULT_RAGAS_MAX_TOKENS = 2000


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvalCase:
    id: str
    question: str
    user_role: str
    user_divisi: str | None
    user_id: UUID | None
    user_email: str | None
    expected_sql: str
    expected_answer: str
    expected_context: dict[str, list[str]]
    notes: str | None = None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run live RAGAS evals for text-to-SQL pipeline.")
    parser.add_argument("--cases", default="evals/ragas/cases.yaml", help="Path to YAML eval cases.")
    parser.add_argument("--out", default="evals/ragas/results", help="Output directory for JSON/CSV reports.")
    parser.add_argument(
        "--include-clarification",
        action="store_true",
        help=(
            "Run ambiguity clarification before SQL generation. "
            "By default evals bypass clarification so SQL metrics can be scored."
        ),
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Case loading
# ---------------------------------------------------------------------------


def load_cases(path: Path) -> list[EvalCase]:
    if not path.exists():
        raise FileNotFoundError(f"Cases file not found: {path}")

    with path.open("r", encoding="utf-8") as file:
        raw_cases = yaml.safe_load(file) or []

    if not isinstance(raw_cases, list):
        raise ValueError("Cases file must contain a YAML list.")

    cases: list[EvalCase] = []
    for index, raw_case in enumerate(raw_cases, start=1):
        _validate_raw_case(index, raw_case)
        cases.append(_parse_raw_case(raw_case))

    if not cases:
        raise ValueError("Cases file must contain at least one case.")
    return cases


def _validate_raw_case(index: int, raw_case: Any) -> None:
    if not isinstance(raw_case, dict):
        raise ValueError(f"Case #{index} must be an object.")
    missing = [field for field in ("id", "question", "user_role") if not raw_case.get(field)]
    if missing:
        raise ValueError(f"Case #{index} missing required field(s): {', '.join(missing)}")
    if not raw_case.get("expected_answer") and not raw_case.get("expected_sql"):
        raise ValueError(f"Case #{index} must include expected_answer or expected_sql.")
    if not raw_case.get("user_id") and not raw_case.get("user_email"):
        raise ValueError(f"Case #{index} must include user_id or user_email.")


def _parse_raw_case(raw_case: dict[str, Any]) -> EvalCase:
    expected_context = raw_case.get("expected_context") or {}
    if not isinstance(expected_context, dict):
        raise ValueError(f"Case {raw_case['id']} expected_context must be an object.")

    return EvalCase(
        id=str(raw_case["id"]),
        question=str(raw_case["question"]),
        user_role=str(raw_case["user_role"]),
        user_divisi=raw_case.get("user_divisi"),
        user_id=UUID(str(raw_case["user_id"])) if raw_case.get("user_id") else None,
        user_email=str(raw_case["user_email"]) if raw_case.get("user_email") else None,
        expected_sql=str(raw_case.get("expected_sql") or "").strip(),
        expected_answer=str(raw_case.get("expected_answer") or raw_case.get("expected_sql") or "").strip(),
        expected_context={
            "tables": [str(v) for v in expected_context.get("tables", [])],
            "columns": [str(v) for v in expected_context.get("columns", [])],
        },
        notes=raw_case.get("notes"),
    )


# ---------------------------------------------------------------------------
# Context builders
# ---------------------------------------------------------------------------


def build_retrieved_contexts(
    db_schema_context: str,
    generated_sql: str,
    rows_returned: int | None,
    query_result: list[dict] | None = None,  # ← tambah parameter ini
) -> list[str]:
    candidates = [
        db_schema_context,
        f"Generated SQL:\n{generated_sql}" if generated_sql else "",
        f"Rows returned: {rows_returned if rows_returned is not None else 0}",
        f"Query result:\n{json.dumps(query_result, ensure_ascii=False, indent=2)}" if query_result else "",
    ]
    return [c for c in candidates if c]


def build_reference_contexts(eval_case: EvalCase) -> list[str]:
    evidence = eval_case.expected_answer or eval_case.expected_sql
    return [f"Expected answer evidence: {evidence}"] if evidence else []


def build_error_contexts(eval_case: EvalCase) -> list[str]:
    """Fallback contexts for pipeline-error rows (no SQL was generated)."""
    evidence = eval_case.expected_answer or eval_case.expected_sql
    return [evidence] if evidence else []


# ---------------------------------------------------------------------------
# SSE stream helpers
# ---------------------------------------------------------------------------


def parse_sse_event(event: str) -> tuple[str | None, str | None]:
    event_type = None
    data = None
    for line in event.strip().splitlines():
        if line.startswith("event: "):
            event_type = line[7:]
        elif line.startswith("data: "):
            data = line[6:]
    return event_type, data


async def collect_stream_response(stream: Any) -> Any:
    from schema.chatSchema import ChatResponse

    metadata: dict[str, Any] = {}
    message_parts: list[str] = []
    async for event in stream:
        event_type, data = parse_sse_event(event)
        if event_type == "metadata" and data:
            metadata = json.loads(data)
        elif event_type == "message" and data:
            message_parts.append(json.loads(data).get("chunk", ""))

    return ChatResponse(**metadata, message="".join(message_parts))


# ---------------------------------------------------------------------------
# Row builders
# ---------------------------------------------------------------------------


def serialize_stages(stages: list[Any]) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    for stage in stages:
        if hasattr(stage, "model_dump"):
            serialized.append(stage.model_dump())
        elif isinstance(stage, dict):
            serialized.append(stage)
        else:
            serialized.append({"stage": str(stage)})
    return serialized


def build_success_row(eval_case: EvalCase, response: Any, db_schema_context: str) -> dict[str, Any]:
    generated_sql = (response.generated_sql or "").strip()
    has_sql = bool(generated_sql)

    return {
        "id": eval_case.id,
        "question": eval_case.question,
        "answer": response.message or generated_sql,
        "generated_sql": generated_sql,
        "expected_sql": eval_case.expected_sql,
        "expected_answer": eval_case.expected_answer,
        "reference": eval_case.expected_answer,
        "contexts": build_retrieved_contexts(
            db_schema_context,
            generated_sql,
            response.rows_returned,
            query_result=response.query_result,  # ← row data dari pipeline
        ),
        "reference_contexts": build_reference_contexts(eval_case),
        "expected_context": eval_case.expected_context,
        "final_narrative": response.message,
        "rows_returned": response.rows_returned,
        "execution_time_ms": response.execution_time_ms,
        "pipeline_stages": serialize_stages(response.pipeline_stages),
        "status": "success" if has_sql else "missing_generated_sql",
        "error": None if has_sql else "ChatResponse.generated_sql was empty.",
        "notes": eval_case.notes,
    }


def build_error_row(
    eval_case: EvalCase,
    status: str,
    error: str,
    db_schema_context: str,
    pipeline_stages: list[Any] | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": eval_case.id,
        "question": eval_case.question,
        "answer": "",
        "generated_sql": "",
        "expected_sql": eval_case.expected_sql,
        "expected_answer": eval_case.expected_answer,
        "reference": eval_case.expected_answer,
        "contexts": build_error_contexts(eval_case),
        "reference_contexts": build_reference_contexts(eval_case),
        "expected_context": eval_case.expected_context,
        "pipeline_context": db_schema_context,
        "status": status,
        "error": error,
        "notes": eval_case.notes,
    }
    if pipeline_stages is not None:
        row["pipeline_stages"] = serialize_stages(pipeline_stages)
    return row


# ---------------------------------------------------------------------------
# Pipeline execution
# ---------------------------------------------------------------------------


async def resolve_user_id(db: Any, eval_case: EvalCase) -> UUID:
    if eval_case.user_id is not None:
        return eval_case.user_id

    from sqlalchemy import select

    from model.User import User

    result = await db.execute(select(User.id).where(User.email == eval_case.user_email))
    user_id = result.scalar_one_or_none()
    if user_id is None:
        raise ValueError(f"User email not found for case {eval_case.id}: {eval_case.user_email}")
    return user_id


async def run_pipeline_case(eval_case: EvalCase, include_clarification: bool = False) -> dict[str, Any]:
    from databaseConfig import AsyncSessionLocal
    from service.chatService import ChatService
    from template.promptTemplate import DB_SCHEMA

    session_id = uuid4()
    async with AsyncSessionLocal() as db:
        db_schema_context = await _build_db_schema_context(db, DB_SCHEMA)

        try:
            user_id = await resolve_user_id(db, eval_case)
            stream = ChatService(db).process_query_stream(
                user_message=eval_case.question,
                user_id=user_id,
                user_role=eval_case.user_role,
                session_id=session_id,
                show_sql=True,
                context_from_clarification=None if include_clarification else {},
            )
            response = await collect_stream_response(stream)
        except Exception as error:
            await db.rollback()
            return build_error_row(eval_case, "pipeline_error", str(error), db_schema_context)

        if response.clarification_questions:
            return build_error_row(
                eval_case,
                "clarification_required",
                response.message,
                db_schema_context,
                pipeline_stages=response.pipeline_stages,
            )

        return build_success_row(eval_case, response, db_schema_context)


async def _build_db_schema_context(db: Any, base_schema: str) -> str:
    from service.columnStatisticsService import ColumnStatisticsService

    try:
        statistics = await ColumnStatisticsService(db).get_statistics_text()
        if statistics:
            return f"{base_schema}\n\nCOLUMN STATISTICS:\n{statistics}"
    except Exception as error:
        return f"{base_schema}\n\nCOLUMN STATISTICS UNAVAILABLE: {error}"

    return base_schema


# ---------------------------------------------------------------------------
# RAGAS evaluation
# ---------------------------------------------------------------------------


def configure_ragas_environment() -> None:
    from configCredidential import get_settings

    settings = get_settings()
    if settings.LLM_API_KEY and not os.getenv("OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = settings.LLM_API_KEY
    if settings.LLM_BASE_URL and not os.getenv("OPENAI_BASE_URL"):
        os.environ["OPENAI_BASE_URL"] = settings.LLM_BASE_URL


def _get_llm_settings() -> tuple[str, str | None]:
    """Returns (api_key, base_url)."""
    from configCredidential import get_settings

    settings = get_settings()
    api_key = os.getenv("OPENAI_API_KEY") or settings.LLM_API_KEY
    base_url = os.getenv("OPENAI_BASE_URL") or settings.LLM_BASE_URL or None
    return api_key, base_url


def _build_judge_llm() -> Any:
    from openai import OpenAI

    api_key, base_url = _get_llm_settings()
    sync_client = OpenAI(api_key=api_key, base_url=base_url)

    return llm_factory(
        model=os.getenv("RAGAS_JUDGE_MODEL", DEFAULT_RAGAS_JUDGE_MODEL),
        client=sync_client,
        max_tokens=int(os.getenv("RAGAS_MAX_TOKENS", DEFAULT_RAGAS_MAX_TOKENS)),
    )


def _build_embeddings() -> Any:
    from ragas.embeddings import embedding_factory

    api_key, base_url = _get_llm_settings()
    if api_key and not os.getenv("OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = api_key
    if base_url and not os.getenv("OPENAI_BASE_URL"):
        os.environ["OPENAI_BASE_URL"] = base_url

    return embedding_factory(
        "openai",
        model=os.getenv("RAGAS_EMBEDDING_MODEL", DEFAULT_RAGAS_EMBEDDING_MODEL),
    )

def _prepare_metrics(judge_llm: Any, embeddings: LangchainEmbeddingsWrapper) -> dict[str, Any]:
    answer_similarity = AnswerSimilarity(embeddings=embeddings)  # ← hapus llm=

    return {
        "answer_correctness": AnswerCorrectness(
            llm=judge_llm,
            answer_similarity=answer_similarity,
        ),
        "answer_relevancy": AnswerRelevancy(llm=judge_llm, embeddings=embeddings),
        "faithfulness": Faithfulness(llm=judge_llm),
        "context_recall": ContextRecall(llm=judge_llm),
        "context_precision": ContextPrecision(llm=judge_llm),
    }


def _strip_insight_section(text: str) -> str:
    """Hapus bagian interpretasi/insight yang tidak bisa diverifikasi dari data."""
    # Hapus dari "💡 Insight" sampai akhir
    text = re.sub(r"💡.*", "", text, flags=re.DOTALL)
    # Hapus kalimat yang mengandung kata-kata subjektif umum
    subjective_patterns = [
        r"[^.]*menunjukkan kinerja[^.]*\.",
        r"[^.]*konsisten dan efektif[^.]*\.",
        r"[^.]*perencanaan.*pelaksanaan[^.]*\.",
        r"[^.]*tidak ada kesenjangan[^.]*\.",
    ]
    for pattern in subjective_patterns:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)
    return text.strip()


def _build_sample(row: dict[str, Any]) -> Any:
    from ragas.dataset_schema import SingleTurnSample

    # Bersihkan answer dari klaim subjektif sebelum scoring
    clean_answer = _strip_insight_section(row["answer"])

    return SingleTurnSample(
        user_input=row["question"],
        response=clean_answer,  # ← pakai yang sudah dibersihkan
        reference=row.get("expected_answer") or row["reference"],
        retrieved_contexts=row["contexts"],
    )


async def _score_row(row: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
    sample = _build_sample(row)
    scores: dict[str, Any] = {}

    for name, metric in metrics.items():
        try:
            result = await metric.single_turn_ascore(sample)
            scores[name] = float(result)
        except Exception as error:
            scores[name] = None
            scores[f"{name}_error"] = str(error)

    return {**row, **scores}


async def evaluate_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Score every successful row using RAGAS ascore API."""
    if not any(row.get("status") == "success" for row in rows):
        return [{**row, "metric_error": "No successful rows to evaluate."} for row in rows]

    configure_ragas_environment()

    try:
        metrics = _prepare_metrics(_build_judge_llm(), _build_embeddings())
    except Exception as error:
        return [{**row, "metric_error": f"Failed to initialise RAGAS metrics: {error}"} for row in rows]

    evaluated: list[dict[str, Any]] = []
    for row in rows:
        if row.get("status") != "success":
            evaluated.append(row)
            continue
        try:
            evaluated.append(await _score_row(row, metrics))
        except Exception as error:
            evaluated.append({**row, "metric_error": str(error)})

    return evaluated


# ---------------------------------------------------------------------------
# Report writing
# ---------------------------------------------------------------------------


def write_reports(rows: list[dict[str, Any]], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    _write_json_report(rows, out_dir / "latest.json")
    _write_json_report(rows, out_dir / f"{timestamp}.json")
    _write_csv_report(rows, out_dir / "latest.csv")
    _write_csv_report(rows, out_dir / f"{timestamp}.csv")


def _write_json_report(rows: list[dict[str, Any]], path: Path) -> None:
    payload = {
        "generated_at": datetime.now().isoformat(),
        "metrics": METRIC_NAMES,
        "results": rows,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _write_csv_report(rows: list[dict[str, Any]], path: Path) -> None:
    list_fields = ("contexts", "reference_contexts", "pipeline_stages")
    dict_fields = ("expected_context",)

    flattened = []
    for row in rows:
        flat = dict(row)
        for field in list_fields:
            flat[field] = json.dumps(row.get(field, []), ensure_ascii=False)
        for field in dict_fields:
            flat[field] = json.dumps(row.get(field, {}), ensure_ascii=False)
        flattened.append(flat)

    pd.DataFrame(flattened).to_csv(path, index=False)


# ---------------------------------------------------------------------------
# Resource cleanup
# ---------------------------------------------------------------------------


async def shutdown_async_resources() -> None:
    try:
        from databaseConfig import engine
        await engine.dispose()
    except Exception:
        pass

    try:
        from service.chatService import llm
        await llm.client.close()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def main() -> None:
    args = parse_args()
    try:
        cases = load_cases(Path(args.cases))
        rows = [
            await run_pipeline_case(eval_case, include_clarification=args.include_clarification)
            for eval_case in cases
        ]
        evaluated_rows = await evaluate_rows(rows)
        write_reports(evaluated_rows, Path(args.out))
        print(f"Wrote RAGAS reports to {args.out}")
    finally:
        await shutdown_async_resources()


if __name__ == "__main__":
    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())