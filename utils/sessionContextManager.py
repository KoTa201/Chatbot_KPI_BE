"""
utils/sessionContextManager.py
Mengelola clarification context per session.
Menyimpan: clarification history, preferences, state.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

logger = logging.getLogger(__name__)

# In-memory session store (TODO: replace dengan Redis untuk production)
_SESSION_STORE: dict[str, dict] = {}
SESSION_TTL_HOURS = 8


class SessionContextManager:
    """Manager untuk session clarification context."""

    @staticmethod
    def create_session_context(session_id: str) -> dict:
        """Buat context baru untuk session."""
        context = {
            "session_id": session_id,
            "clarification_history": [],
            "scope_preferences": {},
            "temporal_preferences": {},
            "metric_preferences": {},
            "clarification_count": 0,
            "last_clarification_at": None,
            "created_at": datetime.now(),
        }
        _SESSION_STORE[session_id] = context
        logger.info(f"[SessionContext] Created context for session {session_id}")
        return context

    @staticmethod
    def get_session_context(session_id: str) -> dict | None:
        """Ambil context untuk session. Auto-create jika tidak ada."""
        if session_id not in _SESSION_STORE:
            # Check TTL: jika sudah lama, hapus
            SessionContextManager._cleanup_expired_sessions()
            return SessionContextManager.create_session_context(session_id)

        # Check TTL untuk session ini
        context = _SESSION_STORE[session_id]
        age = datetime.now() - context.get("created_at", datetime.now())
        if age > timedelta(hours=SESSION_TTL_HOURS):
            logger.info(f"[SessionContext] Session {session_id} expired, recreating")
            del _SESSION_STORE[session_id]
            return SessionContextManager.create_session_context(session_id)

        return context

    @staticmethod
    def add_clarification_to_history(
        session_id: str,
        question: str,
        answer: str,
        ambiguity_type: str,
    ) -> None:
        """Tambah clarification ke riwayat session."""
        context = SessionContextManager.get_session_context(session_id)
        if not context:
            return

        context["clarification_history"].append(
            {
                "question": question,
                "answer": answer,
                "ambiguity_type": ambiguity_type,
                "timestamp": datetime.now().isoformat(),
            }
        )
        context["clarification_count"] = len(context["clarification_history"])
        context["last_clarification_at"] = datetime.now()
        logger.info(
            f"[SessionContext] Added clarification to {session_id}: "
            f"type={ambiguity_type}, count={context['clarification_count']}"
        )

    @staticmethod
    def set_scope_preference(
        session_id: str,
        preference_key: str,
        value: str,
    ) -> None:
        """Simpan preference scope untuk session (e.g., 'divisi' = 'IT')."""
        context = SessionContextManager.get_session_context(session_id)
        if not context:
            return

        context["scope_preferences"][preference_key] = value
        logger.info(
            f"[SessionContext] Set scope preference: {session_id}.{preference_key}={value}"
        )

    @staticmethod
    def get_scope_preference(session_id: str, preference_key: str) -> Optional[str]:
        """Ambil scope preference dari session."""
        context = SessionContextManager.get_session_context(session_id)
        if not context:
            return None
        return context["scope_preferences"].get(preference_key)

    @staticmethod
    def set_temporal_preference(
        session_id: str,
        period_key: str,
        value: str,
    ) -> None:
        """Simpan preference temporal untuk session (e.g., 'period' = 'bulan ini')."""
        context = SessionContextManager.get_session_context(session_id)
        if not context:
            return

        context["temporal_preferences"][period_key] = value
        logger.info(
            f"[SessionContext] Set temporal preference: {session_id}.{period_key}={value}"
        )

    @staticmethod
    def set_metric_preference(
        session_id: str,
        metric_key: str,
        value: str,
    ) -> None:
        """Simpan preference metric untuk session (e.g., 'metric' = 'persentase')."""
        context = SessionContextManager.get_session_context(session_id)
        if not context:
            return

        context["metric_preferences"][metric_key] = value
        logger.info(
            f"[SessionContext] Set metric preference: {session_id}.{metric_key}={value}"
        )

    @staticmethod
    def has_preference(session_id: str, preference_type: str, key: str) -> bool:
        """Check apakah preference sudah ada di session."""
        context = SessionContextManager.get_session_context(session_id)
        if not context:
            return False

        prefs = context.get(f"{preference_type}_preferences", {})
        return key in prefs

    @staticmethod
    def get_clarification_history(session_id: str) -> list[dict]:
        """Ambil riwayat clarification di session."""
        context = SessionContextManager.get_session_context(session_id)
        if not context:
            return []
        return context["clarification_history"]

    @staticmethod
    def clear_session_context(session_id: str) -> None:
        """Hapus context untuk session (logout/session end)."""
        if session_id in _SESSION_STORE:
            del _SESSION_STORE[session_id]
            logger.info(f"[SessionContext] Cleared context for session {session_id}")

    @staticmethod
    def _cleanup_expired_sessions() -> None:
        """Cleanup sessions yang sudah expired."""
        now = datetime.now()
        expired = []
        for sid, context in _SESSION_STORE.items():
            age = now - context.get("created_at", now)
            if age > timedelta(hours=SESSION_TTL_HOURS):
                expired.append(sid)

        for sid in expired:
            del _SESSION_STORE[sid]
            logger.info(f"[SessionContext] Cleaned up expired session {sid}")

    @staticmethod
    def get_stats() -> dict:
        """Get statistics tentang sessions yang aktif."""
        return {
            "active_sessions": len(_SESSION_STORE),
            "sessions": [
                {
                    "session_id": sid,
                    "clarification_count": ctx["clarification_count"],
                    "age_minutes": (
                        (datetime.now() - ctx.get("created_at")).total_seconds() / 60
                    ),
                }
                for sid, ctx in _SESSION_STORE.items()
            ],
        }
