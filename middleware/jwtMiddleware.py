"""
middlewares/jwt_middleware.py
Middleware JWT untuk FastAPI.
Mendukung role: admin, kepala_divisi, karyawan
"""

import json
import re
from typing import Optional
from uuid import UUID

from fastapi import Request, status
from jose import JWTError, jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from config import settings

ALGORITHM = "HS256"

# ------------------------------------------------------------------ #
#  Role constants                                                      #
# ------------------------------------------------------------------ #

ADMIN = "admin"
KEPALA_DIVISI = "kepala_divisi"
KARYAWAN = "karyawan"

ALL_ROLES = {ADMIN, KEPALA_DIVISI, KARYAWAN}


# ------------------------------------------------------------------ #
#  Daftar route yang TIDAK memerlukan token                           #
# ------------------------------------------------------------------ #

PUBLIC_ROUTES: list[tuple[Optional[str], str]] = [
    ("OPTIONS", r"^/api/v1"),
    ("POST",    r"^/api/v1/users/login$"),
    ("POST",    r"^/api/v1/users/refresh$"),
    ("POST",    r"^/api/v1/users/logout$"),
    ("POST",    r"^/api/v1/users/forgot-password$"),
    ("POST",    r"^/api/v1/users/verify-reset-pin$"),
    ("POST",    r"^/api/v1/users/reset-password$"),
    (None,      r"^/docs$"),
    (None,      r"^/redoc$"),
    (None,      r"^/openapi\.json$"),
    (None,      r"^/health$"),
]


# ------------------------------------------------------------------ #
#  Role-based access control (RBAC)                                   #
#                                                                     #
#  Format: (HTTP_METHOD, path_regex, set_of_allowed_roles)            #
#  Gunakan None pada METHOD untuk semua method pada path tsb.         #
#  Urutan penting — rule pertama yang cocok akan dipakai.             #
# ------------------------------------------------------------------ #

ROLE_ROUTES: list[tuple[Optional[str], str, set[str]]] = [

    # ── User management ────────────────────────────────────────────
    # Admin: full CRUD
    # Login tetap boleh untuk semua role
    ("POST",  r"^/api/v1/users/login$",                 ALL_ROLES),
    # Refresh token tetap boleh untuk semua role
    ("POST",  r"^/api/v1/users/refresh$",               ALL_ROLES),
    # Logout tetap boleh untuk semua role
    ("POST",  r"^/api/v1/users/logout$",                ALL_ROLES),
    ("POST",  r"^/api/v1/users/me/change-password$",    ALL_ROLES),
    ("GET",   r"^/api/v1/users/[\w-]+$",                ALL_ROLES),
    ("PATCH", r"^/api/v1/users/[\w-]+$",                ALL_ROLES),
    (None,    r"^/api/v1/users",                        {ADMIN}),
    (None,    r"^/api/v1/chatbots",                     {ADMIN}),
    (None,    r"^/api/v1/ingest",                       {ADMIN, KEPALA_DIVISI}),
    (None,    r"^/api/v1/scheduler",                    {ADMIN, KEPALA_DIVISI}),
    (None,    r"^/api/v1/kpi",                          {ADMIN, KEPALA_DIVISI}),
    (None,    r"^/api/v1/chat",                         ALL_ROLES),

]


# ------------------------------------------------------------------ #
#  Helper                                                              #
# ------------------------------------------------------------------ #

def _is_public_route(method: str, path: str) -> bool:
    for allowed_method, pattern in PUBLIC_ROUTES:
        if allowed_method is not None and allowed_method != method:
            continue
        if re.match(pattern, path):
            return True
    return False


def _get_allowed_roles(method: str, path: str) -> Optional[set[str]]:
    """
    Return set role yang diizinkan untuk kombinasi method+path.
    Return None jika tidak ada rule yang cocok (berarti akses ditolak by default).
    """
    for allowed_method, pattern, roles in ROLE_ROUTES:
        if allowed_method is not None and allowed_method != method:
            continue
        if re.match(pattern, path):
            return roles
    return None


def _extract_token(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None


def _decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


def _json_response(status_code: int, detail: str) -> Response:
    body = json.dumps({"detail": detail}, ensure_ascii=False)
    return Response(
        content=body,
        status_code=status_code,
        media_type="application/json",
    )


# ------------------------------------------------------------------ #
#  Middleware                                                          #
# ------------------------------------------------------------------ #

class JWTMiddleware(BaseHTTPMiddleware):
    """
    Middleware JWT + RBAC.

    Alur:
        1. Public route  → langsung lolos tanpa token
        2. Token absent  → 401
        3. Token invalid → 401
        4. Role check    → 403 jika role tidak diizinkan
        5. Lolos         → inject ke request.state, teruskan ke handler

    request.state setelah lolos:
        .jwt_payload  → dict
        .user_id      → UUID
        .username     → str
        .role         → str  ("admin" | "kepala_divisi" | "karyawan")
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        method = request.method

        # 1. Public routes — skip semua validasi
        if _is_public_route(method, path):
            return await call_next(request)

        # 2. Ambil & validasi token
        token = _extract_token(request.headers.get("Authorization"))
        if not token:
            return _json_response(
                status.HTTP_401_UNAUTHORIZED,
                "Token tidak ditemukan. Sertakan header: Authorization: Bearer <token>",
            )

        # 3. Decode token
        payload = _decode_token(token)
        if payload is None:
            return _json_response(
                status.HTTP_401_UNAUTHORIZED,
                "Token tidak valid atau sudah kadaluarsa.",
            )

        # 4. Klaim wajib
        user_id = payload.get("sub")
        if not user_id:
            return _json_response(
                status.HTTP_401_UNAUTHORIZED,
                "Token tidak mengandung identitas user.",
            )

        role: str = payload.get("role", "")

        # 5. RBAC — cek apakah role diizinkan mengakses endpoint ini
        allowed_roles = _get_allowed_roles(method, path)

        if allowed_roles is None:
            # Tidak ada rule yang cocok → tolak (deny by default)
            return _json_response(
                status.HTTP_403_FORBIDDEN,
                f"Akses ditolak: endpoint tidak terdaftar dalam kebijakan akses.",
            )

        if role not in allowed_roles:
            return _json_response(
                status.HTTP_403_FORBIDDEN,
                f"Akses ditolak: role '{role}' tidak memiliki izin untuk endpoint ini.",
            )

        # 6. Inject ke request.state
        request.state.jwt_payload = payload
        request.state.user_id = UUID(user_id)
        request.state.username = payload.get("username", "")
        request.state.role = role

        return await call_next(request)
