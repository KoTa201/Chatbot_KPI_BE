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

import pandas as pd
import yaml
from datasets import Dataset


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
DEFAULT_RAGAS_EMBEDDING_MODEL = "openai/text-embedding-3-small"


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run live RAGAS evals for text-to-SQL pipeline.")
    parser.add_argument("--cases", default="evals/ragas/cases.yaml", help="Path to YAML eval cases.")
    parser.add_argument("--out", default="evals/ragas/results", help="Output directory for JSON/CSV reports.")
    parser.add_argument(
        "--include-clarification",
        action="store_true",
        help="Run ambiguity clarification before SQL generation. By default evals bypass clarification so SQL metrics can be scored.",
    )
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
        missing = [field for field in ("id", "question", "user_role") if not raw_case.get(field)]
        if missing:
            raise ValueError(f"Case #{index} missing required field(s): {', '.join(missing)}")
        if not raw_case.get("expected_answer") and not raw_case.get("expected_sql"):
            raise ValueError(f"Case #{index} must include expected_answer or expected_sql.")
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
                expected_sql=str(raw_case.get("expected_sql") or "").strip(),
                expected_answer=str(raw_case.get("expected_answer") or raw_case.get("expected_sql") or "").strip(),
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


def build_final_answer_context(eval_case: EvalCase) -> list[str]:
    context = eval_case.expected_answer or eval_case.expected_sql
    return [context] if context else []


def build_reference_contexts(eval_case: EvalCase) -> list[str]:
    context = eval_case.expected_answer or eval_case.expected_sql
    return ["Expected answer evidence: " + context] if context else []


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


def build_pipeline_context(base_context: str, generated_sql: str, rows_returned: int | None) -> str:
    return (
        f"{base_context}"
        f"\n\nGENERATED SQL:\n{generated_sql or ''}"
        f"\n\nPIPELINE EVIDENCE:\nrows_returned={rows_returned if rows_returned is not None else 0}"
    )


def build_success_row(eval_case: EvalCase, response: Any, context: str) -> dict[str, Any]:
    generated_sql = (response.generated_sql or "").strip()
    pipeline_context = build_pipeline_context(
        base_context=context,
        generated_sql=generated_sql,
        rows_returned=response.rows_returned,
    )

    return {
        "id": eval_case.id,
        "question": eval_case.question,
        "answer": response.message or generated_sql,
        "generated_sql": generated_sql,
        "expected_sql": eval_case.expected_sql,
        "sql_ground_truth": eval_case.expected_sql,
        "ground_truth": eval_case.expected_answer,
        "reference": eval_case.expected_answer,
        "ragas_reference": eval_case.expected_answer,
        "expected_answer": eval_case.expected_answer,
        "contexts": build_final_answer_context(eval_case),
        "reference_contexts": build_reference_contexts(eval_case),
        "pipeline_context": pipeline_context,
        "expected_context": eval_case.expected_context,
        "final_narrative": response.message,
        "rows_returned": response.rows_returned,
        "execution_time_ms": response.execution_time_ms,
        "pipeline_stages": serialize_stages(response.pipeline_stages),
        "status": "success" if generated_sql else "missing_generated_sql",
        "error": None if generated_sql else "ChatResponse.generated_sql was empty.",
        "notes": eval_case.notes,
    }


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
            return {
                "id": eval_case.id,
                "question": eval_case.question,
                "answer": "",
                "generated_sql": "",
                "ground_truth": eval_case.expected_sql,
                "reference": eval_case.expected_answer,
                "contexts": build_final_answer_context(eval_case),
                "reference_contexts": build_reference_contexts(eval_case),
                "pipeline_context": context,
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
                "reference": eval_case.expected_answer,
                "contexts": build_final_answer_context(eval_case),
                "reference_contexts": build_reference_contexts(eval_case),
                "pipeline_context": context,
                "expected_context": eval_case.expected_context,
                "status": "clarification_required",
                "error": response.message,
                "pipeline_stages": serialize_stages(response.pipeline_stages),
                "notes": eval_case.notes,
            }

        return build_success_row(eval_case, response, context)


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
                "ground_truth": row.get("expected_answer") or row["reference"],
                "reference": row.get("expected_answer") or row["reference"],
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


def configure_ragas_environment() -> None:
    from configCredidential import get_settings

    settings = get_settings()
    if settings.LLM_API_KEY and not os.getenv("OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = settings.LLM_API_KEY
    if settings.LLM_BASE_URL and not os.getenv("OPENAI_BASE_URL"):
        os.environ["OPENAI_BASE_URL"] = settings.LLM_BASE_URL


class RagasEmbeddingAdapter:
    def __init__(self, embeddings: Any):
        self.embeddings = embeddings

    def embed_text(self, text: str) -> list[float]:
        return self.embeddings.embed_text(text)

    async def aembed_text(self, text: str) -> list[float]:
        return await self.embeddings.aembed_text(text)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return self.embeddings.embed_texts(texts)

    async def aembed_texts(self, texts: list[str]) -> list[list[float]]:
        return await self.embeddings.aembed_texts(texts)

    def embed_query(self, text: str) -> list[float]:
        return self.embed_text(text)

    async def aembed_query(self, text: str) -> list[float]:
        return await self.aembed_text(text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.embed_texts(texts)

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self.aembed_texts(texts)


def build_ragas_embeddings() -> Any:
    from configCredidential import get_settings
    from ragas.embeddings import LiteLLMEmbeddings

    settings = get_settings()
    embeddings = LiteLLMEmbeddings(
        model=os.getenv("RAGAS_EMBEDDING_MODEL", DEFAULT_RAGAS_EMBEDDING_MODEL),
        api_key=os.getenv("OPENAI_API_KEY") or settings.LLM_API_KEY,
        api_base=os.getenv("OPENAI_BASE_URL") or settings.LLM_BASE_URL,
        timeout=int(os.getenv("RAGAS_EMBEDDING_TIMEOUT", "300")),
        max_retries=int(os.getenv("RAGAS_EMBEDDING_MAX_RETRIES", "1")),
    )
    return RagasEmbeddingAdapter(embeddings)


async def evaluate_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not any(row.get("status") == "success" for row in rows):
        return [{**row, "metric_error": "No successful rows to evaluate."} for row in rows]

    try:
        from ragas import evaluate
        from ragas.run_config import RunConfig

        configure_ragas_environment()
        dataset = build_ragas_dataset(rows)
        result = evaluate(
            dataset,
            metrics=load_ragas_metrics(),
            embeddings=build_ragas_embeddings(),
            run_config=RunConfig(
                timeout=int(os.getenv("RAGAS_TIMEOUT", "600")),
                max_retries=int(os.getenv("RAGAS_MAX_RETRIES", "1")),
                max_workers=int(os.getenv("RAGAS_MAX_WORKERS", "3")),
            ),
        )
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
            rows.append(await run_pipeline_case(eval_case, include_clarification=args.include_clarification))
        evaluated_rows = await evaluate_rows(rows)
        write_reports(evaluated_rows, Path(args.out))
        print(f"Wrote RAGAS reports to {args.out}")
    finally:
        await shutdown_async_resources()


if __name__ == "__main__":
    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
