"""
service/clarificationHelpers.py
Pure helper functions for the clarification mechanism.
Extracted from ClarificationService for testability and reuse.
"""

from collections.abc import Mapping
from typing import Any

from schema.clarificationSchema import ClarificationAnswerItem
from service.preferenceTreeService import QAPair

SKIP_OPTION = "Lewati"
FREE_TEXT_OPTION = "Lainnya"
UNKNOWN_AMBIGUITY_TYPE = "unknown"


def effective_answer(answer: ClarificationAnswerItem) -> str:
    """Extract the effective answer from a ClarificationAnswerItem.

    If the user selected 'Lainnya' and provided free_text, use the free_text.
    Otherwise, use the selected_option verbatim.
    """
    if answer.selected_option == FREE_TEXT_OPTION and answer.free_text:
        return answer.free_text
    return answer.selected_option


def question_key(question: str) -> str:
    """Normalize a question string for case-insensitive deduplication."""
    return question.strip().casefold()


def build_qa_set(
    clarification_answers: list[ClarificationAnswerItem],
    log_by_id: Mapping[str, object],
) -> list[QAPair]:
    """Build a list of QAPair from clarification answers and their associated logs.

    Each log provides:
    - level1 = ambiguity_type (or UNKNOWN_AMBIGUITY_TYPE if None)
    - level2 = clarification_question (or question_id as fallback)
    - question = clarification_question (or question_id as fallback)
    - answer = effective_answer(answer_item)
    """
    qa_set: list[QAPair] = []
    for answer in clarification_answers:
        eff = effective_answer(answer)
        if eff.strip() == SKIP_OPTION:
            continue
        log = log_by_id[str(answer.question_id)]
        qa_set.append(
            QAPair(
                level1=getattr(log, "ambiguity_type", None) or UNKNOWN_AMBIGUITY_TYPE,
                level2=getattr(log, "clarification_question", None)
                or str(answer.question_id),
                question=getattr(log, "clarification_question", None)
                or str(answer.question_id),
                answer=eff,
            )
        )
    return qa_set


def build_session_qa_set(
    logs: list[object],
    current_qa_set: list[QAPair],
) -> list[QAPair]:
    """Build full-session QAPairs from all answered logs + current answers.

    Current answers override same question from logs.
    Only include logs where selected_answer exists.
    Deduplicates by question (case-insensitive).
    """
    current_by_question = {
        question_key(pair.question): pair for pair in current_qa_set
    }
    session_pairs: list[QAPair] = []
    seen_questions: set[str] = set()

    # Process logs in reverse order (most recent first)
    for log in reversed(logs):
        q_text = (getattr(log, "clarification_question", None) or "").strip()
        if not q_text:
            continue
        key = question_key(q_text)

        # If current answer exists for this question, use it
        if key in current_by_question:
            pair = current_by_question[key]
        else:
            # Otherwise, use log's answer if it exists and is not "Lewati"
            selected_answer = getattr(log, "selected_answer", None)
            if selected_answer is None or str(selected_answer) == SKIP_OPTION:
                continue
            pair = QAPair(
                level1=getattr(log, "ambiguity_type", None) or UNKNOWN_AMBIGUITY_TYPE,
                level2=q_text,
                question=q_text,
                answer=str(selected_answer),
            )

        # Skip if we've already seen this question
        if key in seen_questions:
            continue
        session_pairs.append(pair)
        seen_questions.add(key)

    # Add any current answers that weren't in logs
    for pair in current_qa_set:
        key = question_key(pair.question)
        if key not in seen_questions:
            session_pairs.append(pair)
            seen_questions.add(key)

    return session_pairs


def answered_question_keys(qa_set: list[QAPair]) -> set[str]:
    """Return a set of normalized question keys from a QAPair list."""
    return {question_key(pair.question) for pair in qa_set}


def filter_unanswered_ambiguities(
    ambiguities: list[Any],
    answered_questions: set[str],
) -> list[Any]:
    """Filter out DetectedAmbiguity objects whose suggested_clarifying_question
    has already been answered (case-insensitive comparison)."""
    return [
        a
        for a in ambiguities
        if question_key(a.suggested_clarifying_question or "")
        not in answered_questions
    ]


def build_fallback_disambiguated_query(
    original_query: str,
    clarification_answers: list[ClarificationAnswerItem],
    additional_constraints: str | None = None,
) -> str:
    """Deterministic fallback for query disambiguation when LLM is unavailable.

    Combines the original query with user answers, skipping 'Lewati' and
    using free_text for 'Lainnya' selections.
    """
    query = original_query.strip()
    additions: list[str] = []
    for answer in clarification_answers:
        if answer.selected_option == SKIP_OPTION:
            continue
        if answer.selected_option == FREE_TEXT_OPTION:
            if answer.free_text and answer.free_text.strip():
                additions.append(answer.free_text.strip())
            continue
        stripped = answer.selected_option.strip()
        if stripped:
            additions.append(stripped)
    if additional_constraints and additional_constraints.strip():
        additions.append(additional_constraints.strip())
    if not additions:
        return query
    return f"{query} ({'; '.join(additions)})"
