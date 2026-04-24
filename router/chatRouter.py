"""
Chat Router — mendefinisikan semua HTTP endpoint untuk chatbot KPI.
Tanggung jawab: routing, HTTP method, status code, response model.
Logika bisnis didelegasikan ke ChatController → ChatService.
"""
from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import StreamingResponse

from service.authService import get_current_user
from controller.chatController import ChatController
from schema.chatSchema import ChatRequest, AuditLogResponse
from model.User import UserORM


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

        # ── History ─────────────────────────────────────────────────── #
        self.router.add_api_route(
            "/history",
            self.get_my_history,
            methods=["GET"],
            response_model=list[AuditLogResponse],
            status_code=status.HTTP_200_OK,
            summary="Riwayat query chatbot milik user yang sedang login",
        )

        # ── Audit ───────────────────────────────────────────────────── #
        self.router.add_api_route(
            "/audit/failed",
            self.get_failed_wireguard_logs,
            methods=["GET"],
            response_model=list[AuditLogResponse],
            status_code=status.HTTP_200_OK,
            summary="[Admin/HRD] Daftar query yang ditolak SQLWireguard",
        )

    # ── Chat handlers ──────────────────────────────────────────────── #

    async def send_message(
        self,
        request: ChatRequest,
        current_user: UserORM = Depends(get_current_user),
        controller: ChatController = Depends(ChatController),
    ):
        """
        Endpoint utama chatbot. Menjalankan pipeline 5 stage:

        1. **NL-to-SQL**: Pertanyaan bahasa Indonesia dikonversi ke SQL via GitHub Models.
        2. **SQLWireguard**: SQL divalidasi keamanannya (whitelist, RLS, injection detection).
        3. **SQL Execution**: SQL yang lolos dieksekusi ke PostgreSQL (read-only).
        4. **Graphic Generation (Opsional)**: Jika user meminta visualisasi, sistem membuat grafik (bar/pie/donut).
        5. **Result Analysis**: Hasil query dianalisis oleh GitHub Models menjadi narasi Bahasa Indonesia.

        **Role access:**
        - `Karyawan`: Hanya melihat data KPI milik sendiri (RLS enforced).
        - `HRD` / `Owner`: Melihat semua data karyawan.
        - `Admin`: Akses penuh read-only.

        **Optional:** Set `show_sql: true` untuk melihat SQL yang dieksekusi (transparansi).
        """
        return await controller.handle_chat(request=request, current_user=current_user)

    async def handle_clarification(
        self,
        request: ChatRequest,
        current_user: UserORM = Depends(get_current_user),
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
        if not request.clarification_answer:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=400,
                detail="clarification_answer harus disertakan untuk endpoint ini"
            )
        return await controller.handle_clarification(request=request, current_user=current_user)

    async def get_my_history(
        self,
        skip: int = Query(default=0, ge=0, description="Offset untuk pagination"),
        limit: int = Query(default=20, ge=1, le=100,
                           description="Jumlah data per halaman"),
        current_user: UserORM = Depends(get_current_user),
        controller: ChatController = Depends(ChatController),
    ):
        """
        Mengembalikan riwayat query chatbot (dari audit log) milik user yang sedang login.
        Diurutkan dari yang terbaru.
        """
        return await controller.handle_get_history(
            skip=skip, limit=limit, current_user=current_user
        )

    async def get_failed_wireguard_logs(
        self,
        skip: int = Query(default=0, ge=0),
        limit: int = Query(default=50, ge=1, le=100),
        current_user: UserORM = Depends(get_current_user),
        controller: ChatController = Depends(ChatController),
    ):
        """
        Mengembalikan semua query yang gagal melewati validasi SQLWireguard.
        Hanya dapat diakses oleh role **Admin** dan **HRD** untuk keperluan monitoring keamanan.
        """
        return await controller.handle_get_audit_all(
            skip=skip, limit=limit, current_user=current_user
        )


# ─── Router instance ───────────────────────────────────────────────────
router = ChatRouter().router
