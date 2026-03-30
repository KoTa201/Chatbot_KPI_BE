"""
routers/auth.py
Mendefinisikan route endpoint authentication & user management.
Semua logika request/response/validation ada di AuthController.

Aturan akses:
- POST   /auth/login                → publik
- GET    /auth/me                   → user login (semua role)
- POST   /auth/me/change-password   → user login (semua role)
- POST   /auth/users                → admin only
- GET    /auth/users                → admin only
- GET    /auth/users/{id}           → admin only
- PATCH  /auth/users/{id}           → admin only
- DELETE /auth/users/{id}           → admin only
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from controller.userController import AuthController
from databaseConfig import get_db
from model.User import UserORM
from schema.authSchema import (
    ChangePasswordRequest,
    LoginRequest,
    MessageResponse,
    TokenResponse,
    UpdateUserRequest,
    UserCreateRequest,
    UserResponse,
)
from service.userService import get_current_user, require_admin

router = APIRouter()


# ------------------------------------------------------------------ #
#  Login                                                               #
# ------------------------------------------------------------------ #

@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Login dan dapatkan JWT access token",
)
async def login(
    payload: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    controller = AuthController(db)
    return await controller.login(payload)


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
    "/users",
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
    "/users",
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
    "/users/{user_id}",
    response_model=UserResponse,
    summary="[Admin] Detail user berdasarkan ID",
)
async def get_user_by_id(
    user_id: int,
    admin: UserORM = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    controller = AuthController(db)
    return await controller.get_user_by_id(user_id, admin)


@router.patch(
    "/users/{user_id}",
    response_model=UserResponse,
    summary="[Admin] Update data user",
)
async def update_user(
    user_id: int,
    payload: UpdateUserRequest,
    admin: UserORM = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    controller = AuthController(db)
    return await controller.update_user(user_id, payload, admin)


@router.delete(
    "/users/{user_id}",
    response_model=MessageResponse,
    summary="[Admin] Hapus user",
)
async def delete_user(
    user_id: int,
    admin: UserORM = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    controller = AuthController(db)
    return await controller.delete_user(user_id, admin)
