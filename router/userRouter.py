
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from controller.userController import AuthController
from databaseConfig import get_db
from model.User import UserORM
from schema.authSchema import (
    ChangePasswordRequest,
    LoginRequest,
    MessageResponse,
    RefreshRequest,         # ← schema baru
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

router = APIRouter()


# ------------------------------------------------------------------ #
#  Login / Refresh / Logout                                            #
# ------------------------------------------------------------------ #

@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Login dan dapatkan access + refresh token",
)
async def login(
    payload: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    controller = AuthController(db)
    return await controller.login(payload)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Perbarui access token menggunakan refresh token",
    description=(
        "Kirim refresh token yang masih valid untuk mendapatkan "
        "pasangan access + refresh token baru. Token lama langsung dinonaktifkan."
    ),
)
async def refresh(
    payload: RefreshRequest,
    db: AsyncSession = Depends(get_db),
):
    controller = AuthController(db)
    return await controller.refresh(payload)


@router.post("/forgot-password", response_model=MessageResponse)
async def forgot_password(
    payload: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    return await AuthController(db).forgot_password(payload)


@router.post("/verify-reset-pin", response_model=ResetTokenResponse)
async def verify_reset_pin(
    payload: VerifyResetPinRequest,
    db: AsyncSession = Depends(get_db),
):
    return await AuthController(db).verify_reset_pin(payload)


@router.post("/reset-password", response_model=MessageResponse)
async def reset_password(
    payload: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    return await AuthController(db).reset_password(payload)


@router.post(
    "/logout",
    response_model=MessageResponse,
    summary="Logout dan cabut refresh token",
    description=(
        "Merevoke refresh token sehingga tidak bisa dipakai ulang. "
        "Client wajib menghapus access token dari sisi mereka sendiri."
    ),
)
async def logout(
    payload: RefreshRequest,
    db: AsyncSession = Depends(get_db),
):
    controller = AuthController(db)
    return await controller.logout(payload)


# ------------------------------------------------------------------ #
#  Profil diri sendiri                                                 #
# ------------------------------------------------------------------ #

@router.get(
    "/me",
    response_model=UserResponse,
    summary="Lihat profil user yang sedang login",
)
async def get_me(
    current_user: UserORM = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    controller = AuthController(db)
    return await controller.get_me(current_user)


@router.post(
    "/me/change-password",
    response_model=MessageResponse,
    summary="Ganti password diri sendiri",
)
async def change_password(
    payload: ChangePasswordRequest,
    current_user: UserORM = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    controller = AuthController(db)
    return await controller.change_password(payload, current_user)


# ------------------------------------------------------------------ #
#  User management (admin only)                                        #
# ------------------------------------------------------------------ #

@router.post(
    "",
    response_model=UserResponse,
    status_code=201,
    summary="[Admin] Tambah user baru",
    description=(
        "Hanya admin yang dapat menambahkan user baru. "
        "Tidak ada endpoint registrasi publik."
    ),
)
async def create_user(
    payload: UserCreateRequest,
    admin: UserORM = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    controller = AuthController(db)
    return await controller.create_user(payload, admin)


@router.get(
    "",
    response_model=dict,
    summary="[Admin] Daftar semua user",
)
async def get_all_users(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    admin: UserORM = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    controller = AuthController(db)
    return await controller.get_all_users(limit, offset, admin)


@router.get(
    "/{user_id}",
    response_model=UserResponse,
    summary="[Admin] Detail user berdasarkan ID",
)
async def get_user_by_id(
    user_id: UUID,
    admin: UserORM = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    controller = AuthController(db)
    return await controller.get_user_by_id(user_id, admin)


@router.patch(
    "/{user_id}",
    response_model=UserResponse,
    summary="[Admin] Update data user",
)
async def update_user(
    user_id: UUID,
    payload: UpdateUserRequest,
    admin: UserORM = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    controller = AuthController(db)
    return await controller.update_user(user_id, payload, admin)


@router.delete(
    "/{user_id}",
    response_model=MessageResponse,
    summary="[Admin] Hapus user",
)
async def delete_user(
    user_id: UUID,
    admin: UserORM = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    controller = AuthController(db)
    return await controller.delete_user(user_id, admin)
