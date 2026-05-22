"""
Chat Controller — validasi request/response untuk endpoint chatbot.
Mengekstrak konteks user dari JWT dan meneruskan ke ChatService.
"""
import json
from collections.abc import AsyncIterator

from fastapi import Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from databaseConfig import get_db
from service.authService import get_current_user
from service.chatService import ChatService
from service.chatSessionService import ChatSessionService
from service.clarificationService import ClarificationService
from schema.chatSchema import ChatRequest, ChatResponse
from schema.sessionSchema import SessionResponse, UpdateSessionTitleRequest
from model.User import User


class ChatController:
    """Validasi & orkestrasi request/response untuk endpoint chatbot."""

    def __init__(self, db: AsyncSession = Depends(get_db)):
        self.db = db

    async def handle_chat(
        self,
        request: ChatRequest,
        current_user: User = Depends(get_current_user),
    ) -> StreamingResponse:
        """
        Handle POST /chat — jalankan pipeline Structured RAG.

        Jika belum ada response atas pertanyaan klarifikasi, lanjut ke pipeline.
        Jika ada response klarifikasi, handle disambiguation terlebih dahulu.
        """
        user_id = str(current_user.id)
        role_value = self._extract_role_value(current_user)
        user_role = self._to_chat_role(role_value)
        user_divisi = None

        if not user_id or not user_role:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token tidak memuat informasi user yang valid.",
            )

        service = ChatService(self.db)
        response = await service.process_query(
            user_message=request.message,
            user_id=UUID(user_id),
            user_role=user_role,
            user_divisi=user_divisi,
            session_id=request.session_id,
            show_sql=request.show_sql,
        )
        return self._build_streaming_response(response)

    async def handle_clarification(
        self,
        request: ChatRequest,
        current_user: User = Depends(get_current_user),
    ) -> StreamingResponse:
        """
        Handle POST /chat/clarification — respons jawaban atas pertanyaan klarifikasi.

        Flow:
        1. User jawab pertanyaan klarifikasi
        2. Sistem disambiguasi query
        3. Query disambiguasi dikirim ke pipeline RAG biasa
        """
        if not request.session_id or not request.clarification_answers:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="session_id dan clarification_answers wajib disertakan",
            )

        user_id = str(current_user.id)
        role_value = self._extract_role_value(current_user)
        user_role = self._to_chat_role(role_value)
        user_divisi = None

        if not user_id or not user_role:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token tidak memuat informasi user yang valid.",
            )

        # Proses clarification response
        clarification_service = ClarificationService(self.db)
        try:
            disambiguation_result = await clarification_service.handle_clarification_response(
                session_id=request.session_id,
                clarification_answers=request.clarification_answers,
                additional_constraints=request.additional_constraints,
                original_query=request.message,
            )
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(e),
            )

        if getattr(disambiguation_result, "needs_more_clarification", False):
            clarification_message = disambiguation_result.clarification_message
            response = ChatResponse(
                session_id=request.session_id,
                message=clarification_message.clarifying_question or "Klarifikasi diperlukan sebelum query KPI dijalankan.",
                clarification_message_answer_options=clarification_message.options,
                clarification_questions=clarification_message.questions,
            )
            return self._build_streaming_response(response)

        # Lanjutkan ke pipeline RAG dengan query yang sudah disambiguasi
        service = ChatService(self.db)
        response = await service.process_query(
            user_message=disambiguation_result.disambiguated_query,
            user_id=UUID(user_id),
            user_role=user_role,
            user_divisi=user_divisi,
            session_id=request.session_id,
            show_sql=request.show_sql,
            context_from_clarification=disambiguation_result,
        )
        return self._build_streaming_response(response)


    @staticmethod
    def _extract_role_value(current_user: User) -> str:
        role = current_user.role.value if hasattr(
            current_user.role, "value") else str(current_user.role)
        return role.strip().lower()

    @staticmethod
    def _to_chat_role(role_value: str) -> str:
        return role_value.strip().lower()

    @staticmethod
    def _message_chunks(message: str) -> list[str]:
        if not message:
            return []
        words = message.split(" ")
        if len(words) == 1:
            return words

        chunks: list[str] = []
        last_index = len(words) - 1
        for index, word in enumerate(words):
            chunks.append(f"{word} " if index < last_index else word)
        return chunks

    def _build_streaming_response(self, response: ChatResponse) -> StreamingResponse:
        payload = response.model_dump(mode="json")
        metadata = {key: value for key,
                    value in payload.items() if key != "message"}
        message = payload.get("message") or ""

        async def _event_stream() -> AsyncIterator[str]:
            yield (
                "event: metadata\n"
                f"data: {json.dumps(metadata, ensure_ascii=False)}\n\n"
            )

            for chunk in self._message_chunks(message):
                yield (
                    "event: message\n"
                    f"data: {json.dumps({'chunk': chunk}, ensure_ascii=False)}\n\n"
                )

            yield "event: done\ndata: {}\n\n"

        return StreamingResponse(
            _event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )
