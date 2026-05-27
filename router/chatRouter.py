"""
Chat Router — mendefinisikan semua HTTP endpoint untuk chatbot KPI.
Tanggung jawab: routing, HTTP method, status code, response model.
Logika bisnis didelegasikan ke ChatController → ChatService.
"""
from uuid import UUID

from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse

from controller.chatSessionController import ChatSessionController
from service.authService import get_current_user
from controller.chatController import ChatController
from schema.chatSchema import ChatRequest, ChatResponse
from schema.sessionSchema import SessionDetailResponse, SessionResponse, UpdateSessionTitleRequest
from model.User import User


class ChatRouter:
    """Router untuk endpoints chatbot KPI."""

    def __init__(self):
        self.router = APIRouter()
        self.setup_routes()

    def _get_controller(self) -> ChatController:
        return ChatController()

    def setup_routes(self):
        """Register all chat routes."""

        # ── Chat ────────────────────────────────────────────────────── #
        self.router.add_api_route(
            "",
            self.send_message,
            methods=["POST"],
            response_class=StreamingResponse,
            status_code=status.HTTP_200_OK,
            summary="Kirim pesan ke chatbot KPI (streaming message)",
        )

        # ── Clarification Response ──────────────────────────────────── #
        self.router.add_api_route(
            "/clarification",
            self.handle_clarification,
            methods=["POST"],
            response_class=StreamingResponse,
            status_code=status.HTTP_200_OK,
            summary="Respond to clarification question (streaming message)",
        )

        # ── Sessions ────────────────────────────────────────────────── #
        self.router.add_api_route(
            "/sessions",
            self.get_sessions,
            methods=["GET"],
            response_model=list[SessionResponse],
            status_code=status.HTTP_200_OK,
            summary="Daftar semua session milik user yang sedang login",
        )

        self.router.add_api_route(
            "/sessions/{session_id}",
            self.get_session_detail,
            methods=["GET"],
            response_model=SessionDetailResponse,
            status_code=status.HTTP_200_OK,
            summary="Detail session beserta riwayat pesan dan pertanyaan klarifikasi",
        )

        self.router.add_api_route(
            "/sessions/{session_id}",
            self.delete_session,
            methods=["DELETE"],
            status_code=status.HTTP_204_NO_CONTENT,
            summary="Hapus session beserta semua pesannya",
        )

        self.router.add_api_route(
            "/sessions/{session_id}/title",
            self.update_session_title,
            methods=["PATCH"],
            response_model=SessionResponse,
            status_code=status.HTTP_200_OK,
            summary="Ubah judul session",
        )

    # ── Chat handlers ──────────────────────────────────────────────── #

    async def send_message(
        self,
        request: ChatRequest,
        current_user: User = Depends(get_current_user),
        controller: ChatController = Depends(ChatController),
    ):
        """
        Endpoint utama chatbot. Menjalankan pipeline 5 stage:

        1. **NL-to-SQL**: Pertanyaan bahasa Indonesia dikonversi ke SQL via LLM.
        2. **SQLWireguard**: SQL divalidasi keamanannya (whitelist, RLS, injection detection).
        3. **SQL Execution**: SQL yang lolos dieksekusi ke PostgreSQL (read-only).
        4. **Graphic Generation (Opsional)**: Jika user meminta visualisasi, sistem membuat grafik (bar/pie/donut).
        5. **Result Analysis**: Hasil query dianalisis oleh LLM menjadi narasi Bahasa Indonesia.

        **Role access:**
        - `Karyawan`: Hanya melihat data KPI milik sendiri (RLS enforced).
        - `kepala_divisi` / `Owner`: Melihat semua data karyawan.
        - `Admin`: Akses penuh read-only.

        **Optional:** Set `show_sql: true` untuk melihat SQL yang dieksekusi (transparansi).
        """
        return await controller.handle_chat(request=request, current_user=current_user)

    async def handle_clarification(
        self,
        request: ChatRequest,
        current_user: User = Depends(get_current_user),
        controller: ChatController = Depends(ChatController),
    ):
        """
        Endpoint untuk menangani response atas pertanyaan klarifikasi.

        **Flow:**
        1. User menerima pertanyaan klarifikasi dari chatbot
        2. User mengirim jawaban (melalui chip pilihan atau teks bebas)
        3. Sistem disambiguasi query berdasarkan jawaban
        4. Query yang sudah jelas diteruskan ke pipeline RAG biasa
        """
        return await controller.handle_clarification(request=request, current_user=current_user)

    async def get_sessions(
        self,
        current_user: User = Depends(get_current_user),
        controller: ChatSessionController = Depends(ChatSessionController),
    ):
        """Kembalikan semua session chatbot milik user yang sedang login."""
        return await controller.handle_get_sessions(current_user=current_user)

    @staticmethod
    async def get_session_detail(
            session_id: UUID,
        current_user: User = Depends(get_current_user),
        controller: ChatSessionController = Depends(ChatSessionController),
    ):
        """Kembalikan detail session, pesan, dan pertanyaan klarifikasi per pesan."""
        return await controller.handle_get_session_detail(
            session_id=session_id, current_user=current_user
        )

    async def delete_session(
        self,
        session_id: UUID,
        current_user: User = Depends(get_current_user),
        controller: ChatSessionController = Depends(ChatSessionController),
    ):
        """
        Hapus session beserta seluruh pesan dan clarification log-nya.
        Hanya pemilik session yang dapat melakukan ini.
        """
        await controller.handle_delete_session(
            session_id=session_id, current_user=current_user
        )

    async def update_session_title(
        self,
        session_id: UUID,
        request: UpdateSessionTitleRequest,
        current_user: User = Depends(get_current_user),
        controller: ChatSessionController = Depends(ChatSessionController),
    ):
        """
        Ubah judul session. Hanya pemilik session yang dapat melakukan ini.
        """
        return await controller.handle_update_session_title(
            session_id=session_id, request=request, current_user=current_user
        )


# ─── Router instance ───────────────────────────────────────────────────
router = ChatRouter().router
