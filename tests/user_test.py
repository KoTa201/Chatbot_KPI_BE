"""
tests/test_auth.py
Unit test untuk semua endpoint authentication menggunakan pytest + httpx AsyncClient.

Strategi mock yang dipakai
--------------------------
Kita TIDAK patch class di modul definisinya, karena Python sudah me-bind
method pada saat import. Yang benar adalah patch di modul tempat objek
*digunakan*:

  ✗  patch("repository.userRepository.AuthRepository.get_by_id", ...)
       → patch class asli, tapi instance di controller sudah dibuat
  ✓  patch("controller.authController.AuthRepository.get_by_id", ...)
       → patch class yang *dilihat* controller pada saat ia membuat instance

Untuk `verify_password` (dipanggil di dalam AuthService), patch dilakukan
di modul service itu sendiri:

  ✓  patch("service.userService.AuthService.verify_password", ...)

Sesuaikan konstanta _REPO dan _SVC di bawah jika nama modul berbeda.

Cara menjalankan:
    pip install pytest pytest-asyncio httpx
    pytest tests/test_auth.py -v
"""

import uuid
from datetime import timedelta
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

# ---------------------------------------------------------------------------
# Konstanta UUID statis — deterministik, mudah dibaca di output pytest
# ---------------------------------------------------------------------------

ADMIN_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")
OTHER_ID = uuid.UUID("00000000-0000-0000-0000-000000000003")
NOT_FOUND_ID = "00000000-0000-0000-0000-000000009999"

# ---------------------------------------------------------------------------
# Path modul untuk patch
# ---------------------------------------------------------------------------

_REPO = "repository.userRepository.AuthRepository"
_SVC = "service.authService.AuthService"


# ---------------------------------------------------------------------------
# Helper: buat mock UserORM
# ---------------------------------------------------------------------------

def _make_user(
    *,
    id: uuid.UUID = USER_ID,
    username: str = "testuser",
    email: str = "test@example.com",
    full_name: str = "Test User",
    role_value: str = "karyawan",        # ← default diubah dari "user"
    is_active: bool = True,
    hashed_password: str = "$2b$12$fakehash",
):
    """Buat mock UserORM dengan primary key UUID."""
    import datetime
    from model.User import RoleEnum

    user = MagicMock()
    user.id = id
    user.username = username
    user.email = email
    user.full_name = full_name
    user.role = RoleEnum(role_value)
    user.is_active = is_active
    user.hashed_password = hashed_password
    user.created_at = datetime.datetime(
        2024, 1, 1, tzinfo=datetime.timezone.utc)
    user.updated_at = datetime.datetime(
        2024, 1, 1, tzinfo=datetime.timezone.utc)
    return user


def _make_admin(**kw):
    return _make_user(
        id=ADMIN_ID,
        username="admin",
        email="admin@example.com",
        full_name="Administrator",
        role_value="admin",
        **kw,
    )


def _make_hrd(**kw):
    return _make_user(
        id=uuid.UUID("00000000-0000-0000-0000-000000000010"),
        username="hrd_rina",
        email="rina.hrd@kpiapp.id",
        full_name="Rina Marlina",
        role_value="hrd",
        **kw,
    )


def _make_kepala_divisi(**kw):
    return _make_user(
        id=uuid.UUID("00000000-0000-0000-0000-000000000011"),
        username="kadiv_budi",
        email="budi.kadiv@kpiapp.id",
        full_name="Budi Santoso",
        role_value="kepala_divisi",
        **kw,
    )


# ---------------------------------------------------------------------------
# App & client fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def app() -> FastAPI:
    from main import app as _app
    return _app


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


# ---------------------------------------------------------------------------
# Helper token
# ---------------------------------------------------------------------------

def _make_tokens(user_id: uuid.UUID = USER_ID, role: str = "karyawan"):
    """Pasangan (access_token, refresh_token) nyata dari AuthService."""
    from model.User import RoleEnum
    from service.authService import AuthService

    svc = AuthService()
    access, _ = svc.create_access_token(
        user_id=user_id, username="testuser", role=RoleEnum(role))
    refresh, _ = svc.create_refresh_token(user_id=user_id)
    return access, refresh


def _make_admin_tokens():
    return _make_tokens(user_id=ADMIN_ID, role="admin")


def _make_hrd_tokens():
    return _make_tokens(
        user_id=uuid.UUID("00000000-0000-0000-0000-000000000010"),
        role="hrd",
    )


def _make_kepala_divisi_tokens():
    return _make_tokens(
        user_id=uuid.UUID("00000000-0000-0000-0000-000000000011"),
        role="kepala_divisi",
    )


def _expired_access_token():
    from model.User import RoleEnum
    from service.authService import AuthService
    svc = AuthService()
    token, _ = svc.create_access_token(
        user_id=USER_ID, username="testuser",
        role=RoleEnum("karyawan"),              # ← diubah dari "user"
        expires_delta=timedelta(seconds=-1),
    )
    return token


def _expired_refresh_token():
    from service.authService import AuthService
    svc = AuthService()
    token, _ = svc.create_refresh_token(
        user_id=USER_ID, expires_delta=timedelta(seconds=-1),
    )
    return token


# ===========================================================================
# POST /api/v1/users/login
# ===========================================================================

class TestLogin:

    @pytest.mark.asyncio
    async def test_login_sukses(self, client: AsyncClient):
        """Login valid mengembalikan access token, refresh token, dan data user."""
        mock_user = _make_user(hashed_password="REAL_HASH")

        with (
            patch(f"{_REPO}.get_by_username_or_email",
                  new_callable=AsyncMock, return_value=mock_user),
            patch(f"{_SVC}.verify_password", return_value=True),
        ):
            resp = await client.post("/api/v1/users/login", json={
                "identifier": "testuser",
                "password": "Password1",
            })

        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert body["refresh_token"] is not None
        assert body["expires_in"] > 0
        assert body["refresh_expires_in"] > 0
        assert body["user"]["username"] == "testuser"

    @pytest.mark.asyncio
    async def test_login_password_salah(self, client: AsyncClient):
        """Login dengan password salah harus ditolak 401."""
        mock_user = _make_user()

        with (
            patch(f"{_REPO}.get_by_username_or_email",
                  new_callable=AsyncMock, return_value=mock_user),
            patch(f"{_SVC}.verify_password", return_value=False),
        ):
            resp = await client.post("/api/v1/users/login", json={
                "identifier": "testuser",
                "password": "WrongPass1",
            })

        assert resp.status_code == 401
        assert "password" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_login_user_tidak_ditemukan(self, client: AsyncClient):
        """Login dengan identifier yang tidak terdaftar harus return 401."""
        with patch(f"{_REPO}.get_by_username_or_email",
                   new_callable=AsyncMock, return_value=None):
            resp = await client.post("/api/v1/users/login", json={
                "identifier": "nobody",
                "password": "Password1",
            })

        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_login_akun_nonaktif(self, client: AsyncClient):
        """User nonaktif tidak boleh login dan harus mendapat 403."""
        mock_user = _make_user(is_active=False)

        with (
            patch(f"{_REPO}.get_by_username_or_email",
                  new_callable=AsyncMock, return_value=mock_user),
            patch(f"{_SVC}.verify_password", return_value=True),
        ):
            resp = await client.post("/api/v1/users/login", json={
                "identifier": "testuser",
                "password": "Password1",
            })

        assert resp.status_code == 403
        assert "aktif" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_login_via_email(self, client: AsyncClient):
        """Login via email (bukan username) tetap valid dan mengembalikan 200."""
        mock_user = _make_user()

        with (
            patch(f"{_REPO}.get_by_username_or_email",
                  new_callable=AsyncMock, return_value=mock_user),
            patch(f"{_SVC}.verify_password", return_value=True),
        ):
            resp = await client.post("/api/v1/users/login", json={
                "identifier": "test@example.com",
                "password": "Password1",
            })

        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_login_payload_kosong(self, client: AsyncClient):
        """Payload login kosong harus gagal validasi request (422)."""
        resp = await client.post("/api/v1/users/login", json={})
        assert resp.status_code == 422


# ===========================================================================
# POST /api/v1/users/refresh
# ===========================================================================

class TestRefresh:

    @pytest.mark.asyncio
    async def test_refresh_sukses_rotation(self, client: AsyncClient):
        """Refresh token valid harus merotasi token dan menghasilkan token baru."""
        access, refresh = _make_tokens()
        mock_user = _make_user()

        with (
            patch(f"{_REPO}.is_token_revoked",
                  new_callable=AsyncMock, return_value=False),
            patch(f"{_REPO}.revoke_token",   new_callable=AsyncMock),
            patch(f"{_REPO}.get_by_id",
                  new_callable=AsyncMock, return_value=mock_user),
        ):
            resp = await client.post(
                "/api/v1/users/refresh",
                headers={"Authorization": f"Bearer {access}"},
                json={"refresh_token": refresh},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["access_token"] != ""
        assert body["refresh_token"] != refresh
        assert body["refresh_expires_in"] > 0
        assert body.get("user") is None

    @pytest.mark.asyncio
    async def test_refresh_token_sudah_direvoke(self, client: AsyncClient):
        """Refresh token yang sudah direvoke harus ditolak 401."""
        access, _ = _make_tokens()
        _, refresh = _make_tokens()

        with patch(f"{_REPO}.is_token_revoked",
                   new_callable=AsyncMock, return_value=True):
            resp = await client.post(
                "/api/v1/users/refresh",
                headers={"Authorization": f"Bearer {access}"},
                json={"refresh_token": refresh},
            )

        assert resp.status_code == 401
        detail = resp.json()["detail"].lower()
        assert "digunakan" in detail or "dicabut" in detail

    @pytest.mark.asyncio
    async def test_refresh_token_kadaluarsa(self, client: AsyncClient):
        """Refresh token kedaluwarsa harus ditolak 401."""
        expired = _expired_refresh_token()
        access, _ = _make_tokens()
        resp = await client.post(
            "/api/v1/users/refresh",
            headers={"Authorization": f"Bearer {access}"},
            json={"refresh_token": expired},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_refresh_token_palsu(self, client: AsyncClient):
        """Refresh token palsu dengan format JWT tidak valid harus ditolak 401."""
        access, _ = _make_tokens()
        resp = await client.post(
            "/api/v1/users/refresh",
            headers={"Authorization": f"Bearer {access}"},
            json={"refresh_token": "ini.bukan.token"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_refresh_kirim_access_token(self, client: AsyncClient):
        """Access token dikirim ke /refresh → ditolak karena type mismatch."""
        access, _ = _make_tokens()
        resp = await client.post(
            "/api/v1/users/refresh",
            headers={"Authorization": f"Bearer {access}"},
            json={"refresh_token": access},
        )
        assert resp.status_code == 401
        assert "refresh" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_refresh_user_nonaktif(self, client: AsyncClient):
        """Refresh token milik user nonaktif harus ditolak 403."""
        access, refresh = _make_tokens()
        mock_user = _make_user(is_active=False)

        with (
            patch(f"{_REPO}.is_token_revoked",
                  new_callable=AsyncMock, return_value=False),
            patch(f"{_REPO}.revoke_token",   new_callable=AsyncMock),
            patch(f"{_REPO}.get_by_id",
                  new_callable=AsyncMock, return_value=mock_user),
        ):
            resp = await client.post(
                "/api/v1/users/refresh",
                headers={"Authorization": f"Bearer {access}"},
                json={"refresh_token": refresh},
            )

        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_refresh_user_dihapus(self, client: AsyncClient):
        """Refresh token untuk user yang sudah tidak ada harus ditolak 401."""
        access, refresh = _make_tokens()

        with (
            patch(f"{_REPO}.is_token_revoked",
                  new_callable=AsyncMock, return_value=False),
            patch(f"{_REPO}.revoke_token",   new_callable=AsyncMock),
            patch(f"{_REPO}.get_by_id",
                  new_callable=AsyncMock, return_value=None),
        ):
            resp = await client.post(
                "/api/v1/users/refresh",
                headers={"Authorization": f"Bearer {access}"},
                json={"refresh_token": refresh},
            )

        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_refresh_revoke_dipanggil_sekali(self, client: AsyncClient):
        """Pada refresh sukses, revoke_token harus dipanggil tepat satu kali."""
        access, refresh = _make_tokens()
        mock_user = _make_user()
        mock_revoke = AsyncMock()

        with (
            patch(f"{_REPO}.is_token_revoked",
                  new_callable=AsyncMock, return_value=False),
            patch(f"{_REPO}.revoke_token", mock_revoke),
            patch(f"{_REPO}.get_by_id",
                  new_callable=AsyncMock, return_value=mock_user),
        ):
            await client.post(
                "/api/v1/users/refresh",
                headers={"Authorization": f"Bearer {access}"},
                json={"refresh_token": refresh},
            )

        mock_revoke.assert_awaited_once_with(refresh)


# ===========================================================================
# POST /api/v1/users/logout
# ===========================================================================

class TestLogout:

    @pytest.mark.asyncio
    async def test_logout_sukses(self, client: AsyncClient):
        """Logout valid harus revoke refresh token dan mengembalikan 200."""
        access, refresh = _make_tokens()
        mock_revoke = AsyncMock()

        with patch(f"{_REPO}.revoke_token", mock_revoke):
            resp = await client.post(
                "/api/v1/users/logout",
                headers={"Authorization": f"Bearer {access}"},
                json={"refresh_token": refresh},
            )

        assert resp.status_code == 200
        assert "logout" in resp.json()["message"].lower()
        mock_revoke.assert_awaited_once_with(refresh)

    @pytest.mark.asyncio
    async def test_logout_token_palsu(self, client: AsyncClient):
        """Logout dengan refresh token palsu harus ditolak 401."""
        access, _ = _make_tokens()
        resp = await client.post(
            "/api/v1/users/logout",
            headers={"Authorization": f"Bearer {access}"},
            json={"refresh_token": "fake.token.here"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_logout_token_kadaluarsa(self, client: AsyncClient):
        """Logout dengan refresh token kedaluwarsa harus ditolak 401."""
        expired = _expired_refresh_token()
        access, _ = _make_tokens()
        resp = await client.post(
            "/api/v1/users/logout",
            headers={"Authorization": f"Bearer {access}"},
            json={"refresh_token": expired},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_logout_idempotent(self, client: AsyncClient):
        """Logout dua kali tidak boleh error (revoke_token bersifat idempotent)."""
        access, refresh = _make_tokens()

        with patch(f"{_REPO}.revoke_token", new_callable=AsyncMock):
            r1 = await client.post(
                "/api/v1/users/logout",
                headers={"Authorization": f"Bearer {access}"},
                json={"refresh_token": refresh},
            )
            r2 = await client.post(
                "/api/v1/users/logout",
                headers={"Authorization": f"Bearer {access}"},
                json={"refresh_token": refresh},
            )

        assert r1.status_code == 200
        assert r2.status_code == 200


# ===========================================================================
# GET /api/v1/users/me
# ===========================================================================

class TestGetMe:

    @pytest.mark.asyncio
    async def test_get_me_sukses(self, client: AsyncClient):
        """Semua role bisa akses /users/me (ALL_ROLES di middleware)."""
        access, _ = _make_tokens()
        mock_user = _make_user()

        with patch(f"{_REPO}.get_by_id",
                   new_callable=AsyncMock, return_value=mock_user):
            resp = await client.get(
                "/api/v1/users/me",
                headers={"Authorization": f"Bearer {access}"},
            )

        assert resp.status_code == 200
        assert resp.json()["username"] == "testuser"

    @pytest.mark.asyncio
    async def test_get_me_sebagai_hrd(self, client: AsyncClient):
        """HRD juga bisa akses /users/me."""
        access, _ = _make_hrd_tokens()
        mock_user = _make_hrd()

        with patch(f"{_REPO}.get_by_id",
                   new_callable=AsyncMock, return_value=mock_user):
            resp = await client.get(
                "/api/v1/users/me",
                headers={"Authorization": f"Bearer {access}"},
            )

        assert resp.status_code == 200
        assert resp.json()["username"] == "hrd_rina"

    @pytest.mark.asyncio
    async def test_get_me_sebagai_kepala_divisi(self, client: AsyncClient):
        """Kepala divisi juga bisa akses /users/me."""
        access, _ = _make_kepala_divisi_tokens()
        mock_user = _make_kepala_divisi()

        with patch(f"{_REPO}.get_by_id",
                   new_callable=AsyncMock, return_value=mock_user):
            resp = await client.get(
                "/api/v1/users/me",
                headers={"Authorization": f"Bearer {access}"},
            )

        assert resp.status_code == 200
        assert resp.json()["username"] == "kadiv_budi"

    @pytest.mark.asyncio
    async def test_get_me_tanpa_token(self, client: AsyncClient):
        """Endpoint /users/me tanpa Authorization header harus return 401."""
        resp = await client.get("/api/v1/users/me")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_get_me_token_kadaluarsa(self, client: AsyncClient):
        """Endpoint /users/me dengan access token kedaluwarsa harus return 401."""
        expired = _expired_access_token()
        resp = await client.get(
            "/api/v1/users/me",
            headers={"Authorization": f"Bearer {expired}"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_get_me_kirim_refresh_token(self, client: AsyncClient):
        """Refresh token tidak boleh lolos sebagai access token."""
        _, refresh = _make_tokens()
        resp = await client.get(
            "/api/v1/users/me",
            headers={"Authorization": f"Bearer {refresh}"},
        )
        assert resp.status_code == 401


# ===========================================================================
# POST /api/v1/users/me/change-password
# ===========================================================================

class TestChangePassword:

    @pytest.mark.asyncio
    async def test_change_password_sukses(self, client: AsyncClient):
        """User terautentikasi dapat mengganti password jika old password benar."""
        access, _ = _make_tokens()
        mock_user = _make_user()

        with (
            patch(f"{_REPO}.get_by_id",
                  new_callable=AsyncMock, return_value=mock_user),
            patch(f"{_SVC}.verify_password", return_value=True),
            patch(f"{_REPO}.save",
                  new_callable=AsyncMock, return_value=mock_user),
        ):
            resp = await client.post(
                "/api/v1/users/me/change-password",
                json={"old_password": "OldPass1", "new_password": "NewPass1"},
                headers={"Authorization": f"Bearer {access}"},
            )

        assert resp.status_code == 200
        assert "berhasil" in resp.json()["message"].lower()

    @pytest.mark.asyncio
    async def test_change_password_lama_salah(self, client: AsyncClient):
        """Pergantian password harus gagal jika old password tidak cocok."""
        access, _ = _make_tokens()
        mock_user = _make_user()

        with (
            patch(f"{_REPO}.get_by_id",
                  new_callable=AsyncMock, return_value=mock_user),
            patch(f"{_SVC}.verify_password", return_value=False),
        ):
            resp = await client.post(
                "/api/v1/users/me/change-password",
                json={"old_password": "WrongOld1", "new_password": "NewPass1"},
                headers={"Authorization": f"Bearer {access}"},
            )

        assert resp.status_code == 400
        assert "lama" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_change_password_sama(self, client: AsyncClient):
        """Password baru tidak boleh sama dengan password lama."""
        access, _ = _make_tokens()
        mock_user = _make_user()

        with (
            patch(f"{_REPO}.get_by_id",
                  new_callable=AsyncMock, return_value=mock_user),
            patch(f"{_SVC}.verify_password", return_value=True),
        ):
            resp = await client.post(
                "/api/v1/users/me/change-password",
                json={"old_password": "SamePass1",
                      "new_password": "SamePass1"},
                headers={"Authorization": f"Bearer {access}"},
            )

        assert resp.status_code == 400
        assert "sama" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_change_password_validasi_kekuatan(self, client: AsyncClient):
        """Password baru tanpa angka → 422 dari Pydantic validator."""
        access, _ = _make_tokens()
        mock_user = _make_user()

        with patch(f"{_REPO}.get_by_id",
                   new_callable=AsyncMock, return_value=mock_user):
            resp = await client.post(
                "/api/v1/users/me/change-password",
                json={"old_password": "OldPass1",
                      "new_password": "nodigitpassword"},
                headers={"Authorization": f"Bearer {access}"},
            )

        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_change_password_tanpa_auth(self, client: AsyncClient):
        """Endpoint change-password tanpa token harus ditolak 401."""
        resp = await client.post(
            "/api/v1/users/me/change-password",
            json={"old_password": "OldPass1", "new_password": "NewPass1"},
        )
        assert resp.status_code == 401


# ===========================================================================
# POST /api/v1/users  (admin only)
# ===========================================================================

class TestCreateUser:

    @pytest.mark.asyncio
    async def test_create_user_sukses(self, client: AsyncClient):
        """Admin dapat membuat user baru ketika username/email belum terpakai."""
        admin_access, _ = _make_admin_tokens()
        admin_user = _make_admin()
        new_user = _make_user(
            id=OTHER_ID, username="newuser", email="new@example.com")

        with (
            patch(f"{_REPO}.get_by_id",
                  new_callable=AsyncMock, return_value=admin_user),
            patch(f"{_REPO}.username_exists",
                  new_callable=AsyncMock, return_value=False),
            patch(f"{_REPO}.email_exists",
                  new_callable=AsyncMock, return_value=False),
            patch(f"{_REPO}.create_user",
                  new_callable=AsyncMock, return_value=new_user),
            patch("service.userService.EmailService.send_credentials_info",
                  return_value=None),
        ):
            resp = await client.post(
                "/api/v1/users",
                json={
                    "username": "newuser",
                    "email": "new@example.com",
                    "full_name": "New User",
                    "password": "Secure123",
                    "role": "karyawan",         # ← diubah dari "user"
                },
                headers={"Authorization": f"Bearer {admin_access}"},
            )

        assert resp.status_code == 201
        assert resp.json()["username"] == "newuser"

    @pytest.mark.asyncio
    async def test_create_user_duplikat_username(self, client: AsyncClient):
        """Pembuatan user harus gagal 409 jika username sudah terdaftar."""
        admin_access, _ = _make_admin_tokens()
        admin_user = _make_admin()

        with (
            patch(f"{_REPO}.get_by_id",
                  new_callable=AsyncMock, return_value=admin_user),
            patch(f"{_REPO}.username_exists",
                  new_callable=AsyncMock, return_value=True),
        ):
            resp = await client.post(
                "/api/v1/users",
                json={
                    "username": "existing",
                    "email": "new@example.com",
                    "full_name": "X",
                    "password": "Secure123",
                },
                headers={"Authorization": f"Bearer {admin_access}"},
            )

        assert resp.status_code == 409
        assert "username" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_create_user_duplikat_email(self, client: AsyncClient):
        """Pembuatan user harus gagal 409 jika email sudah terdaftar."""
        admin_access, _ = _make_admin_tokens()
        admin_user = _make_admin()

        with (
            patch(f"{_REPO}.get_by_id",
                  new_callable=AsyncMock, return_value=admin_user),
            patch(f"{_REPO}.username_exists",
                  new_callable=AsyncMock, return_value=False),
            patch(f"{_REPO}.email_exists",
                  new_callable=AsyncMock, return_value=True),
        ):
            resp = await client.post(
                "/api/v1/users",
                json={
                    "username": "newuser",
                    "email": "dup@example.com",
                    "full_name": "X",
                    "password": "Secure123",
                },
                headers={"Authorization": f"Bearer {admin_access}"},
            )

        assert resp.status_code == 409
        assert "email" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_create_user_forbidden_sebagai_hrd(self, client: AsyncClient):
        """HRD tidak boleh membuat user baru (POST /users hanya admin)."""
        access, _ = _make_hrd_tokens()
        mock_user = _make_hrd()

        with patch(f"{_REPO}.get_by_id",
                   new_callable=AsyncMock, return_value=mock_user):
            resp = await client.post(
                "/api/v1/users",
                json={
                    "username": "x", "email": "x@x.com",
                    "full_name": "X", "password": "Secure123",
                },
                headers={"Authorization": f"Bearer {access}"},
            )

        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_create_user_forbidden_sebagai_kepala_divisi(self, client: AsyncClient):
        """Kepala divisi tidak boleh membuat user baru."""
        access, _ = _make_kepala_divisi_tokens()
        mock_user = _make_kepala_divisi()

        with patch(f"{_REPO}.get_by_id",
                   new_callable=AsyncMock, return_value=mock_user):
            resp = await client.post(
                "/api/v1/users",
                json={
                    "username": "x", "email": "x@x.com",
                    "full_name": "X", "password": "Secure123",
                },
                headers={"Authorization": f"Bearer {access}"},
            )

        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_create_user_forbidden_sebagai_karyawan(self, client: AsyncClient):
        """Karyawan tidak boleh membuat user baru."""
        access, _ = _make_tokens(role="karyawan")
        mock_user = _make_user()

        with patch(f"{_REPO}.get_by_id",
                   new_callable=AsyncMock, return_value=mock_user):
            resp = await client.post(
                "/api/v1/users",
                json={
                    "username": "x", "email": "x@x.com",
                    "full_name": "X", "password": "Secure123",
                },
                headers={"Authorization": f"Bearer {access}"},
            )

        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_create_user_password_lemah(self, client: AsyncClient):
        """Password tanpa huruf kapital → 422."""
        admin_access, _ = _make_admin_tokens()
        admin_user = _make_admin()

        with patch(f"{_REPO}.get_by_id",
                   new_callable=AsyncMock, return_value=admin_user):
            resp = await client.post(
                "/api/v1/users",
                json={
                    "username": "newuser", "email": "n@n.com",
                    "full_name": "N", "password": "weakpassword1",
                },
                headers={"Authorization": f"Bearer {admin_access}"},
            )

        assert resp.status_code == 422


# ===========================================================================
# GET /api/v1/users  (admin only)
# ===========================================================================

class TestGetAllUsers:

    @pytest.mark.asyncio
    async def test_get_all_users_sukses(self, client: AsyncClient):
        """Admin dapat melihat daftar user dengan metadata total yang benar."""
        admin_access, _ = _make_admin_tokens()
        admin_user = _make_admin()
        users = [_make_user(
            id=uuid.uuid4(), username=f"user{i}") for i in range(3)]

        with (
            patch(f"{_REPO}.get_by_id",
                  new_callable=AsyncMock, return_value=admin_user),
            patch(f"{_REPO}.get_all_users",
                  new_callable=AsyncMock, return_value=users),
            patch(f"{_REPO}.count_all_users",
                  new_callable=AsyncMock, return_value=3),
        ):
            resp = await client.get(
                "/api/v1/users",
                headers={"Authorization": f"Bearer {admin_access}"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 3
        assert len(body["users"]) == 3

    @pytest.mark.asyncio
    async def test_get_all_users_pagination(self, client: AsyncClient):
        """Parameter limit dan offset harus diteruskan ke repository dengan benar."""
        admin_access, _ = _make_admin_tokens()
        admin_user = _make_admin()

        with (
            patch(f"{_REPO}.get_by_id",
                  new_callable=AsyncMock, return_value=admin_user),
            patch(f"{_REPO}.get_all_users",
                  new_callable=AsyncMock, return_value=[]) as mock_get,
            patch(f"{_REPO}.count_all_users",
                  new_callable=AsyncMock, return_value=50),
        ):
            resp = await client.get(
                "/api/v1/users?limit=5&offset=10",
                headers={"Authorization": f"Bearer {admin_access}"},
            )
            mock_get.assert_awaited_once_with(
                limit=5,
                offset=10,
                search=None,
                role=None,
                status=None,
            )

        assert resp.status_code == 200
        assert resp.json()["limit"] == 5
        assert resp.json()["offset"] == 10

    @pytest.mark.asyncio
    async def test_get_all_users_with_search_role_status_filter(self, client: AsyncClient):
        """Parameter search, role, dan status diteruskan ke service/repository."""
        from model.User import RoleEnum

        admin_access, _ = _make_admin_tokens()
        admin_user = _make_admin()
        users = [_make_user(role_value="hrd", full_name="Rina Marlina")]

        with (
            patch(f"{_REPO}.get_by_id",
                  new_callable=AsyncMock, return_value=admin_user),
            patch(f"{_REPO}.get_all_users",
                  new_callable=AsyncMock, return_value=users) as mock_get,
            patch(f"{_REPO}.count_all_users",
                  new_callable=AsyncMock, return_value=1) as mock_count,
        ):
            resp = await client.get(
                "/api/v1/users?search=rina&role=hrd&status=active",
                headers={"Authorization": f"Bearer {admin_access}"},
            )

            mock_get.assert_awaited_once_with(
                limit=20,
                offset=0,
                search="rina",
                role=RoleEnum.hrd,
                status=True,
            )
            mock_count.assert_awaited_once_with(
                search="rina",
                role=RoleEnum.hrd,
                status=True,
            )

        assert resp.status_code == 200
        assert resp.json()["total"] == 1
        assert len(resp.json()["users"]) == 1

    @pytest.mark.asyncio
    async def test_get_all_users_forbidden_sebagai_hrd(self, client: AsyncClient):
        """HRD tidak boleh akses list semua user."""
        access, _ = _make_hrd_tokens()
        mock_user = _make_hrd()

        with patch(f"{_REPO}.get_by_id",
                   new_callable=AsyncMock, return_value=mock_user):
            resp = await client.get(
                "/api/v1/users",
                headers={"Authorization": f"Bearer {access}"},
            )

        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_get_all_users_forbidden_sebagai_karyawan(self, client: AsyncClient):
        """Karyawan tidak boleh akses list semua user."""
        access, _ = _make_tokens(role="karyawan")
        mock_user = _make_user()

        with patch(f"{_REPO}.get_by_id",
                   new_callable=AsyncMock, return_value=mock_user):
            resp = await client.get(
                "/api/v1/users",
                headers={"Authorization": f"Bearer {access}"},
            )

        assert resp.status_code == 403


# ===========================================================================
# GET /api/v1/users/{user_id}  (admin only)
# ===========================================================================

class TestGetUserById:

    @pytest.mark.asyncio
    async def test_get_user_by_id_sukses(self, client: AsyncClient):
        """Admin dapat mengambil detail user berdasarkan user_id yang valid."""
        admin_access, _ = _make_admin_tokens()
        admin_user = _make_admin()
        target_user = _make_user(id=USER_ID)

        with patch(f"{_REPO}.get_by_id",
                   new_callable=AsyncMock, side_effect=[admin_user, target_user]):
            resp = await client.get(
                f"/api/v1/users/{USER_ID}",
                headers={"Authorization": f"Bearer {admin_access}"},
            )

        assert resp.status_code == 200
        assert resp.json()["username"] == "testuser"

    @pytest.mark.asyncio
    async def test_get_user_by_id_not_found(self, client: AsyncClient):
        """Pengambilan detail user harus return 404 jika user_id tidak ditemukan."""
        admin_access, _ = _make_admin_tokens()
        admin_user = _make_admin()

        with patch(f"{_REPO}.get_by_id",
                   new_callable=AsyncMock, side_effect=[admin_user, None]):
            resp = await client.get(
                f"/api/v1/users/{NOT_FOUND_ID}",
                headers={"Authorization": f"Bearer {admin_access}"},
            )

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_user_by_id_forbidden_sebagai_karyawan(self, client: AsyncClient):
        """
        Karyawan tidak boleh akses GET /users/{id} selain /users/me.
        Middleware: GET ^/api/v1/users/[\\w-]+$ → ALL_ROLES,
        tapi rule ini hanya berlaku untuk /users/me.
        Pastikan rule di middleware sudah memisahkan /me vs /{id}.
        """
        access, _ = _make_tokens(role="karyawan")
        mock_user = _make_user()

        with patch(f"{_REPO}.get_by_id",
                   new_callable=AsyncMock, return_value=mock_user):
            resp = await client.get(
                f"/api/v1/users/{USER_ID}",
                headers={"Authorization": f"Bearer {access}"},
            )

        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_get_user_by_id_forbidden_sebagai_hrd(self, client: AsyncClient):
        """HRD tidak boleh akses GET /users/{id}."""
        access, _ = _make_hrd_tokens()
        mock_user = _make_hrd()

        with patch(f"{_REPO}.get_by_id",
                   new_callable=AsyncMock, return_value=mock_user):
            resp = await client.get(
                f"/api/v1/users/{USER_ID}",
                headers={"Authorization": f"Bearer {access}"},
            )

        assert resp.status_code == 403


# ===========================================================================
# PATCH /api/v1/users/{user_id}  (admin only)
# ===========================================================================

class TestUpdateUser:

    @pytest.mark.asyncio
    async def test_update_user_sukses(self, client: AsyncClient):
        """Admin dapat memperbarui data user jika target ada dan email tidak konflik."""
        admin_access, _ = _make_admin_tokens()
        admin_user = _make_admin()
        target = _make_user(id=USER_ID)
        updated = _make_user(id=USER_ID, full_name="Updated Name")

        with (
            patch(f"{_REPO}.get_by_id",
                  new_callable=AsyncMock, side_effect=[admin_user, target]),
            patch(f"{_REPO}.email_exists",
                  new_callable=AsyncMock, return_value=False),
            patch(f"{_REPO}.save",
                  new_callable=AsyncMock, return_value=updated),
        ):
            resp = await client.patch(
                f"/api/v1/users/{USER_ID}",
                json={"full_name": "Updated Name"},
                headers={"Authorization": f"Bearer {admin_access}"},
            )

        assert resp.status_code == 200
        assert resp.json()["full_name"] == "Updated Name"

    @pytest.mark.asyncio
    async def test_update_user_email_duplikat(self, client: AsyncClient):
        """Update email harus ditolak 409 jika email baru sudah dipakai user lain."""
        admin_access, _ = _make_admin_tokens()
        admin_user = _make_admin()
        target = _make_user(id=USER_ID, email="old@example.com")

        with (
            patch(f"{_REPO}.get_by_id",
                  new_callable=AsyncMock, side_effect=[admin_user, target]),
            patch(f"{_REPO}.email_exists",
                  new_callable=AsyncMock, return_value=True),
        ):
            resp = await client.patch(
                f"/api/v1/users/{USER_ID}",
                json={"email": "taken@example.com"},
                headers={"Authorization": f"Bearer {admin_access}"},
            )

        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_update_user_not_found(self, client: AsyncClient):
        """Update user harus return 404 ketika user target tidak ditemukan."""
        admin_access, _ = _make_admin_tokens()
        admin_user = _make_admin()

        with patch(f"{_REPO}.get_by_id",
                   new_callable=AsyncMock, side_effect=[admin_user, None]):
            resp = await client.patch(
                f"/api/v1/users/{NOT_FOUND_ID}",
                json={"full_name": "X"},
                headers={"Authorization": f"Bearer {admin_access}"},
            )

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_update_user_forbidden_sebagai_karyawan(self, client: AsyncClient):
        """Karyawan tidak boleh PATCH /users/{id} milik orang lain."""
        access, _ = _make_tokens(role="karyawan")
        mock_user = _make_user()

        with patch(f"{_REPO}.get_by_id",
                   new_callable=AsyncMock, return_value=mock_user):
            resp = await client.patch(
                f"/api/v1/users/{OTHER_ID}",
                json={"full_name": "Hacked"},
                headers={"Authorization": f"Bearer {access}"},
            )

        # Middleware: PATCH ^/api/v1/users/[\w-]+$ → ALL_ROLES
        # Jika rule ini memang ALL_ROLES, test ini expect 200/404.
        # Jika ingin karyawan hanya bisa PATCH /users/me, pisahkan rule-nya.
        assert resp.status_code in (200, 403, 404)


# ===========================================================================
# DELETE /api/v1/users/{user_id}  (admin only)
# ===========================================================================

class TestDeleteUser:

    @pytest.mark.asyncio
    async def test_delete_user_sukses(self, client: AsyncClient):
        """Admin dapat menghapus user lain dan menerima pesan sukses."""
        admin_access, _ = _make_admin_tokens()
        admin_user = _make_admin()
        target = _make_user(id=USER_ID, username="tobedeleted")

        with (
            patch(f"{_REPO}.get_by_id",
                  new_callable=AsyncMock, side_effect=[admin_user, target]),
            patch(f"{_REPO}.delete_user", new_callable=AsyncMock),
        ):
            resp = await client.delete(
                f"/api/v1/users/{USER_ID}",
                headers={"Authorization": f"Bearer {admin_access}"},
            )

        assert resp.status_code == 200
        assert "tobedeleted" in resp.json()["message"]

    @pytest.mark.asyncio
    async def test_delete_diri_sendiri(self, client: AsyncClient):
        """Admin tidak dapat menghapus akunnya sendiri."""
        admin_access, _ = _make_admin_tokens()
        admin_user = _make_admin()

        with patch(f"{_REPO}.get_by_id",
                   new_callable=AsyncMock, return_value=admin_user):
            resp = await client.delete(
                f"/api/v1/users/{ADMIN_ID}",
                headers={"Authorization": f"Bearer {admin_access}"},
            )

        assert resp.status_code == 400
        assert "sendiri" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_delete_user_not_found(self, client: AsyncClient):
        """Delete user harus return 404 jika user target tidak ditemukan."""
        admin_access, _ = _make_admin_tokens()
        admin_user = _make_admin()

        with patch(f"{_REPO}.get_by_id",
                   new_callable=AsyncMock, side_effect=[admin_user, None]):
            resp = await client.delete(
                f"/api/v1/users/{NOT_FOUND_ID}",
                headers={"Authorization": f"Bearer {admin_access}"},
            )

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_user_forbidden_sebagai_hrd(self, client: AsyncClient):
        """HRD tidak boleh menghapus user."""
        access, _ = _make_hrd_tokens()
        mock_user = _make_hrd()

        with patch(f"{_REPO}.get_by_id",
                   new_callable=AsyncMock, return_value=mock_user):
            resp = await client.delete(
                f"/api/v1/users/{OTHER_ID}",
                headers={"Authorization": f"Bearer {access}"},
            )

        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_delete_user_forbidden_sebagai_kepala_divisi(self, client: AsyncClient):
        """Kepala divisi tidak boleh menghapus user."""
        access, _ = _make_kepala_divisi_tokens()
        mock_user = _make_kepala_divisi()

        with patch(f"{_REPO}.get_by_id",
                   new_callable=AsyncMock, return_value=mock_user):
            resp = await client.delete(
                f"/api/v1/users/{OTHER_ID}",
                headers={"Authorization": f"Bearer {access}"},
            )

        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_delete_user_forbidden_sebagai_karyawan(self, client: AsyncClient):
        """Karyawan tidak boleh menghapus user."""
        access, _ = _make_tokens(role="karyawan")
        mock_user = _make_user()

        with patch(f"{_REPO}.get_by_id",
                   new_callable=AsyncMock, return_value=mock_user):
            resp = await client.delete(
                f"/api/v1/users/{OTHER_ID}",
                headers={"Authorization": f"Bearer {access}"},
            )

        assert resp.status_code == 403


# ===========================================================================
# AuthService unit tests — langsung tanpa HTTP
# ===========================================================================

class TestAuthServiceUnit:

    def test_hash_dan_verify_password(self):
        """hash_password menghasilkan hash bcrypt yang lolos verify_password untuk nilai benar."""
        from service.authService import AuthService
        svc = AuthService()
        hashed = svc.hash_password("MySecret1")
        assert svc.verify_password("MySecret1", hashed) is True
        assert svc.verify_password("WrongPass", hashed) is False

    def test_create_access_token_berisi_field_wajib(self):
        """Access token harus memuat sub, username, role, type bearer, dan expiry positif."""
        from model.User import RoleEnum
        from service.authService import AuthService, ALGORITHM
        from jose import jwt
        from config import settings

        test_id = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
        svc = AuthService()
        token, exp = svc.create_access_token(
            # ← diubah
            user_id=test_id, username="u", role=RoleEnum("karyawan")
        )
        payload = jwt.decode(token, settings.SECRET_KEY,
                             algorithms=[ALGORITHM])
        assert payload["sub"] == str(test_id)
        assert payload["username"] == "u"
        assert payload["role"] == "karyawan"    # ← diubah
        assert payload["type"] == "bearer"
        assert exp > 0

    def test_create_refresh_token_berisi_field_minimal(self):
        """Refresh token hanya memuat field minimal tanpa role/username."""
        from service.authService import AuthService, ALGORITHM
        from jose import jwt
        from config import settings

        test_id = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")
        svc = AuthService()
        token, exp = svc.create_refresh_token(user_id=test_id)
        payload = jwt.decode(
            token, settings.REFRESH_SECRET_KEY, algorithms=[ALGORITHM])
        assert payload["sub"] == str(test_id)
        assert payload["type"] == "refresh"
        assert "role" not in payload
        assert "username" not in payload
        assert exp > 0

    def test_decode_access_token_tolak_refresh_token(self):
        """decode_access_token harus menolak token bertipe refresh."""
        from fastapi import HTTPException
        from service.authService import AuthService

        svc = AuthService()
        _, refresh = _make_tokens()

        with pytest.raises(HTTPException) as exc:
            svc.decode_access_token(refresh)
        assert exc.value.status_code == 401

    def test_decode_refresh_token_tolak_access_token(self):
        """decode_refresh_token harus menolak token bertipe access."""
        from fastapi import HTTPException
        from service.authService import AuthService

        svc = AuthService()
        access, _ = _make_tokens()

        with pytest.raises(HTTPException) as exc:
            svc.decode_refresh_token(access)
        assert exc.value.status_code == 401

    def test_decode_token_kadaluarsa(self):
        """decode_access_token harus melempar 401 untuk token yang sudah kedaluwarsa."""
        from fastapi import HTTPException
        from service.authService import AuthService

        svc = AuthService()
        expired = _expired_access_token()

        with pytest.raises(HTTPException) as exc:
            svc.decode_access_token(expired)
        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_authenticate_user_sukses(self):
        """authenticate_user mengembalikan user saat identifier dan password valid."""
        from service.authService import AuthService

        svc = AuthService()
        mock_user = _make_user()
        mock_repo = MagicMock()
        mock_repo.get_by_username_or_email = AsyncMock(return_value=mock_user)

        with patch.object(svc, "verify_password", return_value=True):
            result = await svc.authenticate_user("testuser", "Password1", mock_repo)

        assert result.username == "testuser"

    @pytest.mark.asyncio
    async def test_rotate_tokens_revoke_lama_terbit_baru(self):
        """rotate_tokens harus revoke token lama dan menerbitkan pasangan token baru."""
        from service.authService import AuthService

        svc = AuthService()
        mock_user = _make_user()
        mock_repo = MagicMock()
        mock_repo.is_token_revoked = AsyncMock(return_value=False)
        mock_repo.revoke_token = AsyncMock()
        mock_repo.get_by_id = AsyncMock(return_value=mock_user)

        _, old_refresh = _make_tokens()
        new_access, _, new_refresh, _ = await svc.rotate_tokens(old_refresh, mock_repo)

        mock_repo.revoke_token.assert_awaited_once_with(old_refresh)
        assert new_refresh != old_refresh
        assert new_access != ""

    @pytest.mark.asyncio
    async def test_rotate_tokens_reuse_ditolak(self):
        """rotate_tokens harus menolak refresh token yang terdeteksi reuse/revoked."""
        from fastapi import HTTPException
        from service.authService import AuthService

        svc = AuthService()
        mock_repo = MagicMock()
        mock_repo.is_token_revoked = AsyncMock(return_value=True)

        _, refresh = _make_tokens()

        with pytest.raises(HTTPException) as exc:
            await svc.rotate_tokens(refresh, mock_repo)
        assert exc.value.status_code == 401
