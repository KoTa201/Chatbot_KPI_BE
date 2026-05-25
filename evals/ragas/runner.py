from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pandas as pd
import yaml
from datasets import Dataset


METRIC_NAMES = [
    "answer_correctness",
    "answer_relevancy",
    "faithfulness",
    "context_recall",
    "context_precision",
]


@dataclass(frozen=True)
class EvalCase:
    id: str
    question: str
    user_role: str
    user_divisi: str | None
    user_id: UUID | None
    user_email: str | None
    expected_sql: str
    expected_context: dict[str, list[str]]
    notes: str | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run live RAGAS evals for text-to-SQL pipeline.")
    parser.add_argument("--cases", default="evals/ragas/cases.yaml", help="Path to YAML eval cases.")
    parser.add_argument("--out", default="evals/ragas/results", help="Output directory for JSON/CSV reports.")
    return parser.parse_args()


def load_cases(path: Path) -> list[EvalCase]:
    if not path.exists():
        raise FileNotFoundError(f"Cases file not found: {path}")

    with path.open("r", encoding="utf-8") as file:
        raw_cases = yaml.safe_load(file) or []

    if not isinstance(raw_cases, list):
        raise ValueError("Cases file must contain a YAML list.")

    cases: list[EvalCase] = []
    for index, raw_case in enumerate(raw_cases, start=1):
        if not isinstance(raw_case, dict):
            raise ValueError(f"Case #{index} must be an object.")
        missing = [field for field in ("id", "question", "user_role", "expected_sql") if not raw_case.get(field)]
        if missing:
            raise ValueError(f"Case #{index} missing required field(s): {', '.join(missing)}")
        if not raw_case.get("user_id") and not raw_case.get("user_email"):
            raise ValueError(f"Case #{index} must include user_id or user_email.")

        expected_context = raw_case.get("expected_context") or {}
        if not isinstance(expected_context, dict):
            raise ValueError(f"Case {raw_case['id']} expected_context must be an object.")

        cases.append(
            EvalCase(
                id=str(raw_case["id"]),
                question=str(raw_case["question"]),
                user_role=str(raw_case["user_role"]),
                user_divisi=raw_case.get("user_divisi"),
                user_id=UUID(str(raw_case["user_id"])) if raw_case.get("user_id") else None,
                user_email=str(raw_case["user_email"]) if raw_case.get("user_email") else None,
                expected_sql=str(raw_case["expected_sql"]).strip(),
                expected_context={
                    "tables": [str(value) for value in expected_context.get("tables", [])],
                    "columns": [str(value) for value in expected_context.get("columns", [])],
                },
                notes=raw_case.get("notes"),
            )
        )

    if not cases:
        raise ValueError("Cases file must contain at least one case.")
    return cases


def build_reference_contexts(expected_context: dict[str, list[str]]) -> list[str]:
    parts: list[str] = []
    tables = expected_context.get("tables") or []
    columns = expected_context.get("columns") or []
    if tables:
        parts.append("Expected tables: " + ", ".join(tables))
    if columns:
        parts.append("Expected columns: " + ", ".join(columns))
    return ["\n".join(parts)] if parts else []


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


async def run_pipeline_case(eval_case: EvalCase) -> dict[str, Any]:
    from databaseConfig import AsyncSessionLocal
    from service.chatService import ChatService
    from service.columnStatisticsService import ColumnStatisticsService
    from template.promptTemplate import DB_SCHEMA

    session_id = uuid4()
    async with AsyncSessionLocal() as db:
        context = DB_SCHEMA
        try:
            statistics = await ColumnStatisticsService(db).build_nl_to_sql_statistics()
            if statistics:
                context = f"{DB_SCHEMA}\n\nCOLUMN STATISTICS:\n{statistics}"
        except Exception as error:
            context = f"{DB_SCHEMA}\n\nCOLUMN STATISTICS UNAVAILABLE: {error}"

        try:
            user_id = await resolve_user_id(db, eval_case)
            response = await ChatService(db).process_query(
                user_message=eval_case.question,
                user_id=user_id,
                user_role=eval_case.user_role,
                user_divisi=eval_case.user_divisi,
                session_id=session_id,
                show_sql=True,
            )
        except Exception as error:
            await db.rollback()
            return {
                "id": eval_case.id,
                "question": eval_case.question,
                "answer": "",
                "generated_sql": "",
                "ground_truth": eval_case.expected_sql,
                "reference": eval_case.expected_sql,
                "contexts": [context],
                "reference_contexts": build_reference_contexts(eval_case.expected_context),
                "expected_context": eval_case.expected_context,
                "status": "pipeline_error",
                "error": str(error),
                "notes": eval_case.notes,
            }

        if response.clarification_questions:
            return {
                "id": eval_case.id,
                "question": eval_case.question,
                "answer": "",
                "generated_sql": "",
                "ground_truth": eval_case.expected_sql,
                "reference": eval_case.expected_sql,
                "contexts": [context],
                "reference_contexts": build_reference_contexts(eval_case.expected_context),
                "expected_context": eval_case.expected_context,
                "status": "clarification_required",
                "error": response.message,
                "pipeline_stages": serialize_stages(response.pipeline_stages),
                "notes": eval_case.notes,
            }

        generated_sql = (response.generated_sql or "").strip()
        return {
            "id": eval_case.id,
            "question": eval_case.question,
            "answer": generated_sql,
            "generated_sql": generated_sql,
            "ground_truth": eval_case.expected_sql,
            "reference": eval_case.expected_sql,
            "contexts": [context],
            "reference_contexts": build_reference_contexts(eval_case.expected_context),
            "expected_context": eval_case.expected_context,
            "final_narrative": response.message,
            "rows_returned": response.rows_returned,
            "execution_time_ms": response.execution_time_ms,
            "pipeline_stages": serialize_stages(response.pipeline_stages),
            "status": "success" if generated_sql else "missing_generated_sql",
            "error": None if generated_sql else "ChatResponse.generated_sql was empty.",
            "notes": eval_case.notes,
        }


def load_ragas_metrics() -> list[Any]:
    from ragas.metrics import answer_correctness, answer_relevancy, context_precision, context_recall, faithfulness

    return [answer_correctness, answer_relevancy, faithfulness, context_recall, context_precision]


def build_ragas_dataset(rows: list[dict[str, Any]]) -> Dataset:
    scorable_rows = [row for row in rows if row.get("status") == "success"]
    return Dataset.from_list(
        [
            {
                "question": row["question"],
                "answer": row["answer"],
                "ground_truth": row["ground_truth"],
                "reference": row["reference"],
                "contexts": row["contexts"],
                "reference_contexts": row["reference_contexts"],
            }
            for row in scorable_rows
        ]
    )


def merge_scores(rows: list[dict[str, Any]], scores: list[dict[str, Any]]) -> list[dict[str, Any]]:
    score_index = 0
    merged: list[dict[str, Any]] = []
    for row in rows:
        output = dict(row)
        if row.get("status") == "success" and score_index < len(scores):
            for key, value in scores[score_index].items():
                if key in METRIC_NAMES:
                    output[key] = value
            score_index += 1
        merged.append(output)
    return merged


async def evaluate_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not any(row.get("status") == "success" for row in rows):
        return [{**row, "metric_error": "No successful rows to evaluate."} for row in rows]

    try:
        from ragas import evaluate

        dataset = build_ragas_dataset(rows)
        result = evaluate(dataset, metrics=load_ragas_metrics())
        scores = result.to_pandas().to_dict(orient="records")
        return merge_scores(rows, scores)
    except Exception as error:
        return [{**row, "metric_error": str(error)} for row in rows]


def write_reports(rows: list[dict[str, Any]], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    latest_json = out_dir / "latest.json"
    latest_csv = out_dir / "latest.csv"
    timestamp_json = out_dir / f"{timestamp}.json"
    timestamp_csv = out_dir / f"{timestamp}.csv"

    payload = {
        "generated_at": datetime.now().isoformat(),
        "metrics": METRIC_NAMES,
        "results": rows,
    }
    json_text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    latest_json.write_text(json_text, encoding="utf-8")
    timestamp_json.write_text(json_text, encoding="utf-8")

    flattened = []
    for row in rows:
        flattened.append(
            {
                **row,
                "contexts": json.dumps(row.get("contexts", []), ensure_ascii=False),
                "reference_contexts": json.dumps(row.get("reference_contexts", []), ensure_ascii=False),
                "expected_context": json.dumps(row.get("expected_context", {}), ensure_ascii=False),
                "pipeline_stages": json.dumps(row.get("pipeline_stages", []), ensure_ascii=False),
            }
        )
    frame = pd.DataFrame(flattened)
    frame.to_csv(latest_csv, index=False)
    frame.to_csv(timestamp_csv, index=False)


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


async def main() -> None:
    args = parse_args()
    try:
        cases = load_cases(Path(args.cases))
        rows = []
        for eval_case in cases:
            rows.append(await run_pipeline_case(eval_case))
        evaluated_rows = await evaluate_rows(rows)
        write_reports(evaluated_rows, Path(args.out))
        print(f"Wrote RAGAS reports to {args.out}")
    finally:
        await shutdown_async_resources()


if __name__ == "__main__":
    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
