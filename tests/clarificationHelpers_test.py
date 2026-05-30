"""
tests/clarificationHelpers_test.py
Test suite for clarification helper pure functions extracted from ClarificationService.
"""

from types import SimpleNamespace
from uuid import uuid4

from schema.clarificationSchema import ClarificationAnswerItem, DetectedAmbiguity
from utils.helper.clarificationHelpers import (
    effective_answer,
    build_qa_set,
    build_session_qa_set,
    filter_unanswered_ambiguities,
    build_fallback_disambiguated_query,
)


# ---------------------------------------------------------------------------
# effective_answer
# ---------------------------------------------------------------------------

def test_effective_answer_uses_free_text_for_lainnya():
    """When selected_option is 'Lainnya' and free_text is provided, use free_text."""
    answer = ClarificationAnswerItem(
        question_id="q1",
        selected_option="Lainnya",
        free_text="Gunakan weighted achievement score",
    )
    assert effective_answer(answer) == "Gunakan weighted achievement score"


def test_effective_answer_uses_selected_option_otherwise():
    """When selected_option is NOT 'Lainnya', always use selected_option."""
    answer = ClarificationAnswerItem(
        question_id="q1",
        selected_option="Achievement %",
        free_text="some text",  # should be ignored
    )
    assert effective_answer(answer) == "Achievement %"


def test_effective_answer_lainnya_without_free_text_falls_back_to_selected():
    """When selected_option is 'Lainnya' but free_text is None/empty, return selected_option."""
    answer = ClarificationAnswerItem(
        question_id="q1",
        selected_option="Lainnya",
        free_text=None,
    )
    assert effective_answer(answer) == "Lainnya"


# ---------------------------------------------------------------------------
# build_qa_set
# ---------------------------------------------------------------------------

def test_build_qa_set_uses_log_question_and_type_and_effective_answer():
    """build_qa_set uses log's ambiguity_type as level1, clarifying_question as
    level2 and question, and effective_answer as answer."""
    q1_id = str(uuid4())
    answers = [
        ClarificationAnswerItem(
            question_id=q1_id,
            selected_option="Achievement %",
        ),
    ]
    log_by_id = {
        q1_id: SimpleNamespace(
            ambiguity_type="AmbiSchema",
            clarification_question="'Terbaik' merujuk ke metrik apa?",
        ),
    }

    qa_set = build_qa_set(answers, log_by_id)
    assert len(qa_set) == 1
    assert qa_set[0].level1 == "AmbiSchema"
    assert qa_set[0].level2 == "'Terbaik' merujuk ke metrik apa?"
    assert qa_set[0].question == "'Terbaik' merujuk ke metrik apa?"
    assert qa_set[0].answer == "Achievement %"


def test_build_qa_set_uses_unknown_for_missing_ambiguity_type():
    """build_qa_set uses 'unknown' as level1 when log's ambiguity_type is None."""
    q1_id = str(uuid4())
    answers = [
        ClarificationAnswerItem(question_id=q1_id, selected_option="Ya"),
    ]
    log_by_id = {
        q1_id: SimpleNamespace(
            ambiguity_type=None,
            clarification_question="Apakah termasuk divisi A?",
        ),
    }

    qa_set = build_qa_set(answers, log_by_id)
    assert qa_set[0].level1 == "unknown"


def test_build_qa_set_uses_lainnya_free_text():
    """build_qa_set correctly resolves effective_answer for 'Lainnya' with free_text."""
    q1_id = str(uuid4())
    answers = [
        ClarificationAnswerItem(
            question_id=q1_id,
            selected_option="Lainnya",
            free_text="custom metric",
        ),
    ]
    log_by_id = {
        q1_id: SimpleNamespace(
            ambiguity_type="AmbiSchema",
            clarification_question="Metrik mana?",
        ),
    }

    qa_set = build_qa_set(answers, log_by_id)
    assert qa_set[0].answer == "custom metric"


def test_build_qa_set_excludes_lewati_answers():
    """build_qa_set excludes answers where selected_option == 'Lewati'
    so they do not enter PreferenceTree preferences."""
    q1_id = str(uuid4())
    q2_id = str(uuid4())
    answers = [
        ClarificationAnswerItem(question_id=q1_id, selected_option='Achievement %'),
        ClarificationAnswerItem(question_id=q2_id, selected_option='Lewati'),
    ]
    log_by_id = {
        q1_id: SimpleNamespace(
            ambiguity_type='AmbiSchema',
            clarification_question='Metrik mana?',
        ),
        q2_id: SimpleNamespace(
            ambiguity_type='AmbiRef',
            clarification_question='Divisi mana?',
        ),
    }

    qa_set = build_qa_set(answers, log_by_id)
    assert len(qa_set) == 1
    assert qa_set[0].answer == 'Achievement %'
    assert qa_set[0].question == 'Metrik mana?'


def test_build_qa_set_all_lewati_returns_empty():
    """When all answers are 'Lewati', build_qa_set returns empty
    because skip means no preference."""
    q1_id = str(uuid4())
    q2_id = str(uuid4())
    answers = [
        ClarificationAnswerItem(question_id=q1_id, selected_option='Lewati'),
        ClarificationAnswerItem(question_id=q2_id, selected_option='Lewati'),
    ]
    log_by_id = {
        q1_id: SimpleNamespace(
            ambiguity_type='AmbiSchema',
            clarification_question='Q1?',
        ),
        q2_id: SimpleNamespace(
            ambiguity_type='AmbiRef',
            clarification_question='Q2?',
        ),
    }

    qa_set = build_qa_set(answers, log_by_id)
    assert len(qa_set) == 0


# ---------------------------------------------------------------------------
# build_session_qa_set
# ---------------------------------------------------------------------------

def test_build_session_qa_set_current_answers_override_history():
    """When a question appears in both logs and current qa_set, the current
    answer should take precedence (override)."""
    logs = [
        SimpleNamespace(
            clarification_question="Metrik mana yang dimaksud?",
            ambiguity_type="AmbiSchema",
            selected_answer="Realisasi",
        ),
    ]
    current = build_qa_set(
        [
            ClarificationAnswerItem(
                question_id="q1",
                selected_option="Achievement %",
            ),
        ],
        {
            "q1": SimpleNamespace(
                ambiguity_type="AmbiSchema",
                clarification_question="Metrik mana yang dimaksud?",
            ),
        },
    )

    session_qa = build_session_qa_set(logs, current)

    # Should only have one entry, with the current answer
    assert len(session_qa) == 1
    assert session_qa[0].answer == "Achievement %"


def test_build_session_qa_set_includes_historical_answers():
    """build_session_qa_set includes historical log answers for questions not
    in the current qa_set."""
    logs = [
        SimpleNamespace(
            clarification_question="Periode mana?",
            ambiguity_type="AmbiRef",
            selected_answer="Q1 2025",
        ),
    ]
    current: list = []

    session_qa = build_session_qa_set(logs, current)

    assert len(session_qa) == 1
    assert session_qa[0].question == "Periode mana?"
    assert session_qa[0].answer == "Q1 2025"
    assert session_qa[0].level1 == "AmbiRef"
    assert session_qa[0].level2 == "Periode mana?"


def test_build_session_qa_set_skips_logs_without_selected_answer():
    """build_session_qa_set should skip logs where selected_answer is None."""
    logs = [
        SimpleNamespace(
            clarification_question="Metrik mana?",
            ambiguity_type="AmbiSchema",
            selected_answer=None,
        ),
    ]
    current: list = []

    session_qa = build_session_qa_set(logs, current)

    assert len(session_qa) == 0


def test_build_session_qa_set_deduplicates_by_question():
    """build_session_qa_set should not include duplicate questions (case-insensitive)."""
    logs = [
        SimpleNamespace(
            clarification_question="metrik mana?",
            ambiguity_type="AmbiSchema",
            selected_answer="Realisasi",
        ),
        SimpleNamespace(
            clarification_question="Metrik Mana?",
            ambiguity_type="AmbiSchema",
            selected_answer="Achievement %",
        ),
    ]
    current: list = []

    session_qa = build_session_qa_set(logs, current)

    assert len(session_qa) == 1
    # Should use most recent (first in reversed logs)
    assert session_qa[0].answer == "Achievement %"


# ---------------------------------------------------------------------------
# filter_unanswered_ambiguities
# ---------------------------------------------------------------------------

def test_filter_unanswered_ambiguities_removes_answered_question():
    """Filter out DetectedAmbiguity where suggested_clarifying_question has
    already been answered."""
    ambiguities = [
        DetectedAmbiguity(
            ambiguity_type="AmbiSchema",
            suggested_clarifying_question="Metrik mana yang dimaksud?",
            answer_options=["Achievement %", "Realisasi"],
        ),
        DetectedAmbiguity(
            ambiguity_type="AmbiRef",
            suggested_clarifying_question="Periode mana yang dimaksud?",
            answer_options=["Q1 2025", "Q2 2025"],
        ),
    ]
    answered_questions = {"metrik mana yang dimaksud?"}

    remaining = filter_unanswered_ambiguities(ambiguities, answered_questions)

    assert len(remaining) == 1
    assert remaining[0].suggested_clarifying_question == "Periode mana yang dimaksud?"


def test_filter_unanswered_ambiguities_handles_empty_ambiguities():
    """filter_unanswered_ambiguities should handle empty list gracefully."""
    remaining = filter_unanswered_ambiguities([], {"p"})
    assert remaining == []


def test_filter_unanswered_ambiguities_handles_none_question():
    """filter_unanswered_ambiguities should not crash on None suggested_clarifying_question."""
    ambiguities = [
        DetectedAmbiguity(
            ambiguity_type="AmbiSchema",
            suggested_clarifying_question=None,
            answer_options=["A", "B"],
        ),
    ]
    answered_questions: set[str] = set()

    remaining = filter_unanswered_ambiguities(ambiguities, answered_questions)
    # None question should not be matched, stays in result
    assert len(remaining) == 1


# ---------------------------------------------------------------------------
# build_fallback_disambiguated_query
# ---------------------------------------------------------------------------

def test_build_fallback_disambiguated_query_combines_answers_and_constraints():
    """build_fallback_disambiguated_query combines original query with answers
    and additional constraints."""
    result = build_fallback_disambiguated_query(
        original_query="Tampilkan performa terbaik",
        clarification_answers=[
            ClarificationAnswerItem(
                question_id="q1",
                selected_option="Achievement %",
            ),
        ],
        additional_constraints="hanya divisi aktif",
    )

    assert "Tampilkan performa terbaik" in result
    assert "Achievement %" in result
    assert "hanya divisi aktif" in result


def test_build_fallback_disambiguated_query_skips_lewati():
    """build_fallback_disambiguated_query should skip answers with selected_option
    'Lewati'."""
    result = build_fallback_disambiguated_query(
        original_query="Tampilkan performa terbaik",
        clarification_answers=[
            ClarificationAnswerItem(
                question_id="q1",
                selected_option="Lewati",
            ),
            ClarificationAnswerItem(
                question_id="q2",
                selected_option="Lainnya",
                free_text="gunakan weighted score",
            ),
        ],
    )

    assert "Lewati" not in result
    assert "gunakan weighted score" in result


def test_build_fallback_disambiguated_query_no_additions_returns_original():
    """When there are no additions (all Lewati or empty), return original query."""
    result = build_fallback_disambiguated_query(
        original_query="Tampilkan performa terbaik",
        clarification_answers=[
            ClarificationAnswerItem(
                question_id="q1",
                selected_option="Lewati",
            ),
        ],
    )

    assert result == "Tampilkan performa terbaik"


def test_build_fallback_disambiguated_query_without_additional_constraints():
    """build_fallback_disambiguated_query without additional_constraints still works."""
    result = build_fallback_disambiguated_query(
        original_query="Tampilkan KPI",
        clarification_answers=[
            ClarificationAnswerItem(
                question_id="q1",
                selected_option="Achievement %",
            ),
        ],
    )

    assert result == "Tampilkan KPI (Achievement %)"


# ---------------------------------------------------------------------------
# build_session_qa_set -- Lewati exclusion (regression)
# ---------------------------------------------------------------------------

def test_build_session_qa_set_excludes_historical_lewati_answers():
    """Historical logs where selected_answer == 'Lewati' should not become
    PreferenceTree preferences."""
    logs = [
        SimpleNamespace(
            clarification_question='Periode mana yang dimaksud?',
            ambiguity_type='AmbiRef',
            selected_answer='Lewati',
        ),
        SimpleNamespace(
            clarification_question='Metrik mana?',
            ambiguity_type='AmbiSchema',
            selected_answer='Achievement %',
        ),
    ]
    current: list = []

    session_qa = build_session_qa_set(logs, current)

    assert len(session_qa) == 1
    assert session_qa[0].question == 'Metrik mana?'
    assert session_qa[0].answer == 'Achievement %'


def test_build_session_qa_set_excludes_all_lewati_historical():
    """When ALL historical logs have selected_answer == 'Lewati',
    none should appear in the session QA set."""
    logs = [
        SimpleNamespace(
            clarification_question='Periode mana?',
            ambiguity_type='AmbiRef',
            selected_answer='Lewati',
        ),
        SimpleNamespace(
            clarification_question='Divisi mana?',
            ambiguity_type='AmbiSchema',
            selected_answer='Lewati',
        ),
    ]
    current: list = []

    session_qa = build_session_qa_set(logs, current)

    assert len(session_qa) == 0


# ---------------------------------------------------------------------------
# build_fallback_disambiguated_query -- whitespace-only additional_constraints (regression)
# ---------------------------------------------------------------------------

def test_build_fallback_whitespace_only_constraints_returns_original():
    """When additional_constraints is whitespace-only (or empty after strip),
    no empty parens should be appended -- return the original query."""
    from schema.clarificationSchema import ClarificationAnswerItem
    result = build_fallback_disambiguated_query(
        original_query='Tampilkan performa',
        clarification_answers=[
            ClarificationAnswerItem(
                question_id='q1',
                selected_option='Lewati',
            ),
        ],
        additional_constraints='   ',
    )
    assert result == 'Tampilkan performa'
    assert '()' not in result


def test_build_fallback_whitespace_only_constraints_with_answers():
    """Whitespace-only additional_constraints should not add empty '()'
    when there are valid answers present."""
    from schema.clarificationSchema import ClarificationAnswerItem
    result = build_fallback_disambiguated_query(
        original_query='Tampilkan performa',
        clarification_answers=[
            ClarificationAnswerItem(
                question_id='q1',
                selected_option='Achievement %',
            ),
        ],
        additional_constraints='  \t \n  ',
    )
    # Only the valid answer should appear, not empty constraints
    assert result == 'Tampilkan performa (Achievement %)'
    assert '()' not in result
    assert ';' not in result or result.count(';') <= 0


def test_build_fallback_empty_string_constraints():
    """Empty string additional_constraints (falsy) should have no effect."""
    from schema.clarificationSchema import ClarificationAnswerItem
    result = build_fallback_disambiguated_query(
        original_query='Tampilkan performa',
        clarification_answers=[
            ClarificationAnswerItem(
                question_id='q1',
                selected_option='Achievement %',
            ),
        ],
        additional_constraints='',
    )
    assert result == 'Tampilkan performa (Achievement %)'
    assert '()' not in result


# ---------------------------------------------------------------------------
# build_fallback_disambiguated_query -- blank value guards (regression)
# ---------------------------------------------------------------------------

def test_build_fallback_skips_lainnya_with_blank_free_text():
    """When selected_option is 'Lainnya' but free_text is empty/whitespace,
    no empty segment should be added to the fallback query."""
    from schema.clarificationSchema import ClarificationAnswerItem
    result = build_fallback_disambiguated_query(
        original_query='Tampilkan performa',
        clarification_answers=[
            ClarificationAnswerItem(
                question_id='q1',
                selected_option='Lainnya',
                free_text='   ',
            ),
            ClarificationAnswerItem(
                question_id='q2',
                selected_option='Achievement %',
            ),
        ],
    )
    # Should not have empty separator: "()" or "(;)" 
    assert result == 'Tampilkan performa (Achievement %)'
    assert '()' not in result
    assert '(;' not in result


def test_build_fallback_skips_blank_selected_option():
    """When selected_option is blank or whitespace-only, no empty segment
    should be appended to additions."""
    from schema.clarificationSchema import ClarificationAnswerItem
    result = build_fallback_disambiguated_query(
        original_query='Tampilkan performa',
        clarification_answers=[
            ClarificationAnswerItem(
                question_id='q1',
                selected_option='   ',
                free_text=None,
            ),
            ClarificationAnswerItem(
                question_id='q2',
                selected_option='Realisasi',
            ),
        ],
    )
    assert result == 'Tampilkan performa (Realisasi)'
    assert '()' not in result


def test_build_fallback_returns_original_when_all_answers_blank():
    """When every answer produces no valid addition (all blank/Lewati/Lainnya
    without free_text), the original query is returned verbatim."""
    from schema.clarificationSchema import ClarificationAnswerItem
    result = build_fallback_disambiguated_query(
        original_query='Tampilkan performa',
        clarification_answers=[
            ClarificationAnswerItem(
                question_id='q1',
                selected_option='Lewati',
            ),
            ClarificationAnswerItem(
                question_id='q2',
                selected_option='Lainnya',
                free_text=None,
            ),
            ClarificationAnswerItem(
                question_id='q3',
                selected_option='',
            ),
        ],
    )
    assert result == 'Tampilkan performa'
