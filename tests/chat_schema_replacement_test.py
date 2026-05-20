from model.Base import Base
from model.ChatSession import ChatSession
from model.ChatMessage import ChatMessage
from model.ClarificationQuestion import ClarificationQuestion


def test_chat_schema_tables_are_registered():
    assert ChatSession.__tablename__ == "chat_sessions"
    assert ChatMessage.__tablename__ == "chat_messages"
    assert ClarificationQuestion.__tablename__ == "clarification_questions"

    assert "chatbot_audit_log" not in Base.metadata.tables
    assert "clarification_logs" not in Base.metadata.tables


def test_chat_sessions_columns_match_schema_doc():
    columns = set(ChatSession.__table__.columns.keys())

    assert columns == {
        "session_id",
        "session_name",
        "start_at",
        "end_at",
        "user_id",
        "chatbot_id",
    }
    assert ChatSession.__table__.primary_key.columns.keys() == ["session_id"]


def test_chat_messages_columns_match_schema_doc():
    columns = set(ChatMessage.__table__.columns.keys())

    assert columns == {
        "message_id",
        "message",
        "is_sender_chatbot",
        "send_at",
        "session_id",
    }
    assert ChatMessage.__table__.primary_key.columns.keys() == ["message_id"]


def test_clarification_questions_columns_match_schema_doc():
    columns = set(ClarificationQuestion.__table__.columns.keys())

    assert columns == {
        "clarification_question_id",
        "ambiguous_phrase",
        "ambiguity_type",
        "clarification_question",
        "answer_options",
        "user_answer",
        "created_at",
        "message_id",
    }
    assert ClarificationQuestion.__table__.primary_key.columns.keys() == [
        "clarification_question_id"
    ]
