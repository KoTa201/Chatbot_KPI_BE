"""
middlewares/jwt_middleware.py
Middleware JWT untuk FastAPI.

"""

import json
import re
from typing import Optional

from fastapi import Request, status
from jose import JWTError, jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from config import settings

ALGORITHM = "HS256"

# ------------------------------------------------------------------ #
#  Daftar route yang TIDAK memerlukan token                           #
# ------------------------------------------------------------------ #
# Format: (HTTP_METHOD, path_regex)
# Gunakan None pada METHOD untuk mengizinkan semua method pada path tsb.

PUBLIC_ROUTES: list[tuple[Optional[str], str]] = [
    ("POST", r"^/auth/login$"),          # login
    (None,   r"^/docs$"),                # Swagger UI
    (None,   r"^/redoc$"),               # ReDoc
    (None,   r"^/openapi\.json$"),       # OpenAPI schema
    (None,   r"^/health$"),              # health check (jika ada)
]


# ------------------------------------------------------------------ #
#  Helper                                                              #
# ------------------------------------------------------------------ #

def _is_public_route(method: str, path: str) -> bool:
    """Return True jika kombinasi method+path termasuk public route."""
    for allowed_method, pattern in PUBLIC_ROUTES:
        if allowed_method is not None and allowed_method != method:
            continue
        if re.match(pattern, path):
            return True
    return False


def _extract_token(authorization: Optional[str]) -> Optional[str]:
    """
    Ambil token dari header 'Authorization: Bearer <token>'.
    Return None jika header tidak ada atau formatnya salah.
    """
    if not authorization:
        return None
    parts = authorization.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None


def _decode_token(token: str) -> Optional[dict]:
    """
    Decode dan validasi JWT. Return payload dict jika valid,
    None jika token expired atau signature invalid.
    """
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


def _json_response(status_code: int, detail: str) -> Response:
    """Buat JSON error response secara manual (tanpa FastAPI JSONResponse)."""
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
    Middleware yang memvalidasi JWT pada setiap request non-publik.

    Setelah validasi berhasil, payload token disimpan di:
        request.state.jwt_payload  → dict  (e.g. {"sub": "1", "role": "admin", ...})
        request.state.user_id      → int
        request.state.username     → str
        request.state.role         → str   ("admin" | "user")

    Penggunaan di controller/dependency (opsional, jika tidak pakai get_current_user):
        def some_endpoint(request: Request):
            user_id = request.state.user_id
            role    = request.state.role
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # 1. Lewati validasi untuk public routes
        if _is_public_route(request.method, request.url.path):
            return await call_next(request)

        # 2. Ambil token dari header Authorization
        token = _extract_token(request.headers.get("Authorization"))
        if not token:
            return _json_response(
                status.HTTP_401_UNAUTHORIZED,
                "Token tidak ditemukan. Sertakan header: Authorization: Bearer <token>",
            )

        # 3. Decode dan validasi token
        payload = _decode_token(token)
        if payload is None:
            return _json_response(
                status.HTTP_401_UNAUTHORIZED,
                "Token tidak valid atau sudah kadaluarsa.",
            )

        # 4. Pastikan klaim wajib ada di dalam payload
        user_id = payload.get("sub")
        if not user_id:
            return _json_response(
                status.HTTP_401_UNAUTHORIZED,
                "Token tidak mengandung identitas user.",
            )

        # 5. Inject payload ke request.state agar bisa diakses downstream
        request.state.jwt_payload = payload
        request.state.user_id = int(user_id)
        request.state.username = payload.get("username", "")
        request.state.role = payload.get("role", "")

        # 6. Teruskan request ke handler berikutnya
        return await call_next(request)
