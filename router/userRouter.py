
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from controller.authController import AuthController
from controller.userController import UserController
from databaseConfig import get_db
from model.User import RoleEnum, UserORM
from schema.authSchema import (
    ChangePasswordRequest,
    LoginRequest,
    MessageResponse,
    RefreshRequest,
    TokenResponse,
    UpdateUserRequest,
    UserCreateRequest,
    UserResponse,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    ResetTokenResponse,
    VerifyResetPinRequest,
)
from service.authService import get_current_user, require_admin


class UserRouter:
    """Router untuk endpoints user management dan authentication."""

    def __init__(self):
        self.router = APIRouter()
        self.auth_controller: AuthController | None = None
        self.user_controller: UserController | None = None
        self.setup_routes()

    def setup_routes(self):
        """Register all user routes."""
        # Auth routes
        self.router.add_api_route("/login", self.login, methods=[
                                  "POST"], response_model=TokenResponse, summary="Login dan dapatkan access + refresh token")
        self.router.add_api_route("/refresh", self.refresh, methods=[
                                  "POST"], response_model=TokenResponse, summary="Perbarui access token")
        self.router.add_api_route("/forgot-password", self.forgot_password,
                                  methods=["POST"], response_model=MessageResponse)
        self.router.add_api_route("/verify-reset-pin", self.verify_reset_pin,
                                  methods=["POST"], response_model=ResetTokenResponse)
        self.router.add_api_route(
            "/reset-password", self.reset_password, methods=["POST"], response_model=MessageResponse)
        self.router.add_api_route("/logout", self.logout, methods=[
                                  "POST"], response_model=MessageResponse, summary="Logout dan cabut refresh token")

        # Profile routes
        self.router.add_api_route(
            "/me", self.get_me, methods=["GET"], response_model=UserResponse, summary="Lihat profil user")
        self.router.add_api_route("/me/change-password", self.change_password, methods=[
                                  "POST"], response_model=MessageResponse, summary="Ganti password diri sendiri")

        # Admin user management routes
        self.router.add_api_route("", self.create_user, methods=[
                                  "POST"], response_model=UserResponse, status_code=201, summary="[Admin] Tambah user baru")
        self.router.add_api_route("", self.get_all_users, methods=[
                                  "GET"], response_model=dict, summary="[Admin] Daftar semua user")
        self.router.add_api_route("/{user_id}", self.get_user_by_id, methods=[
                                  "GET"], response_model=UserResponse, summary="[Admin] Detail user")
        self.router.add_api_route("/{user_id}", self.update_user, methods=[
                                  "PATCH"], response_model=UserResponse, summary="[Admin] Update data user")
        self.router.add_api_route("/{user_id}", self.delete_user, methods=[
                                  "DELETE"], response_model=MessageResponse, summary="[Admin] Hapus user")

    # ─── Auth endpoints ───────────────────────────────────────────────────────

    async def login(self, payload: LoginRequest, db: AsyncSession = Depends(get_db)):
        self.auth_controller = AuthController(db)
        return await self.auth_controller.login(payload)

    async def refresh(
        self,
        payload: RefreshRequest,
        db: AsyncSession = Depends(get_db),
    ):
        self.auth_controller = AuthController(db)
        return await self.auth_controller.refresh(payload)

    async def forgot_password(self, payload: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
        self.auth_controller = AuthController(db)
        return await self.auth_controller.forgot_password(payload)

    async def verify_reset_pin(self, payload: VerifyResetPinRequest, db: AsyncSession = Depends(get_db)):
        self.auth_controller = AuthController(db)
        return await self.auth_controller.verify_reset_pin(payload)

    async def reset_password(self, payload: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
        self.auth_controller = AuthController(db)
        return await self.auth_controller.reset_password(payload)

    async def logout(self, payload: RefreshRequest, db: AsyncSession = Depends(get_db)):
        self.auth_controller = AuthController(db)
        return await self.auth_controller.logout(payload)

    # ─── Profile endpoints ─────────────────────────────────────────────────────

    async def get_me(self, current_user: UserORM = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
        self.auth_controller = AuthController(db)
        return await self.auth_controller.get_me(current_user)

    async def change_password(self, payload: ChangePasswordRequest, current_user: UserORM = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
        self.auth_controller = AuthController(db)
        return await self.auth_controller.change_password(payload, current_user)

    # ─── Admin user management endpoints ───────────────────────────────────────

    async def create_user(self, payload: UserCreateRequest, admin: UserORM = Depends(require_admin), db: AsyncSession = Depends(get_db)):
        if not self.user_controller:
            self.user_controller = UserController(db)
        return await self.user_controller.create_user(payload, admin)

    async def get_all_users(
        self,
        limit: int = Query(default=20, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        search: str | None = Query(
            default=None,
            description="Cari user berdasarkan username, full_name, atau email",
        ),
        role: RoleEnum | None = Query(
            default=None,
            description="Filter role user",
        ),
        status: str | None = Query(
            default=None,
            description="Filter status user: active atau inactive",
        ),
        admin: UserORM = Depends(require_admin),
        db: AsyncSession = Depends(get_db),
    ):
        if not self.user_controller:
            self.user_controller = UserController(db)
        return await self.user_controller.get_all_users(
            limit=limit,
            offset=offset,
            admin=admin,
            search=search,
            role=role,
            user_status=status,
        )

    async def get_user_by_id(self, user_id: UUID, admin: UserORM = Depends(require_admin), db: AsyncSession = Depends(get_db)):
        if not self.user_controller:
            self.user_controller = UserController(db)
        return await self.user_controller.get_user_by_id(user_id, admin)

    async def update_user(self, user_id: UUID, payload: UpdateUserRequest, admin: UserORM = Depends(require_admin), db: AsyncSession = Depends(get_db)):
        if not self.user_controller:
            self.user_controller = UserController(db)
        return await self.user_controller.update_user(user_id, payload, admin)

    async def delete_user(self, user_id: UUID, admin: UserORM = Depends(require_admin), db: AsyncSession = Depends(get_db)):
        if not self.user_controller:
            self.user_controller = UserController(db)
        return await self.user_controller.delete_user(user_id, admin)


# ─── Router instance ─────────────────────────────────────────────────────
router = UserRouter().router
