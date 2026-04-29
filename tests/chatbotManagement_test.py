"""
test_chatbot.py — Test suite lengkap untuk modul manajemen chatbot.
Endpoint: POST, GET /, GET /{id}, PATCH /{id}, DELETE /{id}

Jalankan:
    pytest tests/test_chatbot.py -v
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.future import select
from sqlalchemy.pool import StaticPool
from sqlalchemy import text
from uuid import uuid4
from typing import AsyncGenerator

from databaseConfig import Base
from databaseConfig import get_db
from model.Chatbot import Chatbot, AuthorityEnum  # noqa: F401
from model.User import UserORM, RoleEnum
from service.authService import AuthService
from main import app

pytestmark = pytest.mark.asyncio

# ─── DB in-memory (SQLite async) ─────────────────────────────────────────────

DATABASE_URL = "sqlite+aiosqlite:///:memory:"

engine_test = create_async_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

AsyncSessionTest = async_sessionmaker(
    bind=engine_test,
    expire_on_commit=False,
    class_=AsyncSession,
)


async def override_get_db():
    async with AsyncSessionTest() as session:
        yield session


app.dependency_overrides[get_db] = override_get_db


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_db():
    """Buat semua tabel sekali sebelum seluruh test berjalan."""
    async with engine_test.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine_test.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(autouse=True)
async def clean_db():
    """Bersihkan tabel chatbots sebelum setiap test agar tidak saling pengaruh."""
    yield
    async with AsyncSessionTest() as session:
        await session.execute(text("DELETE FROM chatbots"))
        await session.execute(text("DELETE FROM users"))
        await session.commit()


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    auth_service = AuthService()
    admin = UserORM(
        username=f"admin_{uuid4().hex[:8]}",
        email=f"admin_{uuid4().hex[:8]}@example.com",
        full_name="Admin Test",
        hashed_password=auth_service.hash_password("Password1!"),
        role=RoleEnum.admin,
        is_active=True,
    )
    async with AsyncSessionTest() as session:
        session.add(admin)
        await session.commit()
        await session.refresh(admin)

    access_token, _ = auth_service.create_access_token(
        user_id=admin.id,
        username=admin.username,
        role=admin.role,
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {access_token}"},
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def raw_client() -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def role_tokens(db_session: AsyncSession) -> dict[str, str]:
    """Buat user aktif untuk setiap role lalu generate access token-nya."""
    auth_service = AuthService()
    tokens: dict[str, str] = {}

    for role in (RoleEnum.admin, RoleEnum.kepala_divisi, RoleEnum.karyawan):
        suffix = uuid4().hex[:8]
        user = UserORM(
            username=f"{role.value}_{suffix}",
            email=f"{role.value}_{suffix}@example.com",
            full_name=f"{role.value.title()} Test",
            hashed_password=auth_service.hash_password("Password1!"),
            role=role,
            is_active=True,
        )
        db_session.add(user)
        await db_session.flush()

        token, _ = auth_service.create_access_token(
            user_id=user.id,
            username=user.username,
            role=user.role,
        )
        tokens[role.value] = token

    await db_session.commit()
    return tokens


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionTest() as session:
        yield session


# ─── Helper ───────────────────────────────────────────────────────────────────

def make_payload(
    nama: str = "HR Assistant",
    otoritas: str = "HRD",
    addon_prompt: str | None = "Kamu adalah asisten HRD yang ramah.",
) -> dict:
    return {"nama_chatbot": nama, "otoritas": otoritas, "addon_prompt": addon_prompt}


async def seed_chatbot(session: AsyncSession, **kwargs) -> Chatbot:
    """Insert chatbot langsung ke DB tanpa melalui API."""
    defaults = {
        "nama_chatbot": "Seed Bot",
        "otoritas": AuthorityEnum.HRD,
        "addon_prompt": "Prompt awal.",
        "is_active": True,
    }
    chatbot = Chatbot(**{**defaults, **kwargs})
    session.add(chatbot)
    await session.commit()
    await session.refresh(chatbot)
    return chatbot


# ══════════════════════════════════════════════════════════════════════════════
# RBAC /api/v1/chatbots/
# ══════════════════════════════════════════════════════════════════════════════

class TestChatbotRBAC:

    async def test_admin_can_access_chatbot_module(self, raw_client: AsyncClient, role_tokens: dict[str, str]):
        """Role admin boleh akses module chatbot."""
        res = await raw_client.get(
            "/api/v1/chatbots/",
            headers={"Authorization": f"Bearer {role_tokens['admin']}"},
        )

        assert res.status_code == 200

    @pytest.mark.parametrize("role", ["kepala_divisi", "karyawan"])
    async def test_non_admin_cannot_access_chatbot_module(
        self,
        role: str,
        raw_client: AsyncClient,
        role_tokens: dict[str, str],
    ):
        """Role non-admin harus ditolak ketika akses module chatbot."""
        res = await raw_client.get(
            "/api/v1/chatbots/",
            headers={"Authorization": f"Bearer {role_tokens[role]}"},
        )

        assert res.status_code == 403
        assert "Akses ditolak" in res.json()["detail"]

    async def test_chatbot_module_requires_token(self, raw_client: AsyncClient):
        """Tanpa token, endpoint chatbot harus return 401."""
        res = await raw_client.get("/api/v1/chatbots/")

        assert res.status_code == 401


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/v1/chatbots/
# ══════════════════════════════════════════════════════════════════════════════

class TestCreateChatbot:

    async def test_create_hrd_success(self, client: AsyncClient):
        """POST chatbot HRD dengan semua field lengkap harus return 201."""
        res = await client.post("/api/v1/chatbots/", json=make_payload())

        assert res.status_code == 201
        data = res.json()
        assert data["nama_chatbot"] == "HR Assistant"
        assert data["otoritas"] == "HRD"
        assert data["addon_prompt"] == "Kamu adalah asisten HRD yang ramah."
        assert data["is_active"] is True
        assert "id" in data
        assert "created_at" in data
        assert "updated_at" in data

    async def test_create_karyawan_success(self, client: AsyncClient):
        """POST chatbot Karyawan harus return 201."""
        res = await client.post("/api/v1/chatbots/", json=make_payload(nama="Karyawan Bot", otoritas="Karyawan"))

        assert res.status_code == 201
        assert res.json()["otoritas"] == "Karyawan"

    async def test_create_without_addon_prompt(self, client: AsyncClient):
        """addon_prompt bersifat opsional — boleh null."""
        res = await client.post("/api/v1/chatbots/", json=make_payload(nama="Minimal Bot", addon_prompt=None))

        assert res.status_code == 201
        assert res.json()["addon_prompt"] is None

    async def test_create_same_otoritas_deactivates_previous_active(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        """Create chatbot aktif baru dengan otoritas sama harus nonaktifkan chatbot aktif lama."""
        first = await client.post("/api/v1/chatbots/", json=make_payload(nama="HR Bot Lama", otoritas="HRD"))
        second = await client.post("/api/v1/chatbots/", json=make_payload(nama="HR Bot Baru", otoritas="HRD"))

        assert first.status_code == 201
        assert second.status_code == 201

        first_id = first.json()["id"]
        second_id = second.json()["id"]
        result = await db_session.execute(
            select(Chatbot).where(Chatbot.otoritas == AuthorityEnum.HRD)
        )
        status_by_id = {str(chatbot.id): chatbot.is_active for chatbot in result.scalars().all()}

        assert status_by_id[first_id] is False
        assert status_by_id[second_id] is True

    async def test_create_duplicate_nama_returns_409(self, client: AsyncClient):
        """Nama chatbot yang sudah ada harus return 409 Conflict."""
        payload = make_payload(nama="Duplikat Bot")
        await client.post("/api/v1/chatbots/", json=payload)
        res = await client.post("/api/v1/chatbots/", json=payload)

        assert res.status_code == 409
        assert "sudah digunakan" in res.json()["detail"]

    async def test_create_duplicate_nama_case_insensitive(self, client: AsyncClient):
        """Duplikat nama tidak peka huruf besar/kecil."""
        await client.post("/api/v1/chatbots/", json=make_payload(nama="MyBot"))
        res = await client.post("/api/v1/chatbots/", json=make_payload(nama="mybot"))

        assert res.status_code == 409

    async def test_create_missing_nama_returns_422(self, client: AsyncClient):
        """nama_chatbot wajib — jika tidak ada harus return 422."""
        res = await client.post("/api/v1/chatbots/", json={"otoritas": "HRD"})

        assert res.status_code == 422

    async def test_create_missing_otoritas_returns_422(self, client: AsyncClient):
        """otoritas wajib — jika tidak ada harus return 422."""
        res = await client.post("/api/v1/chatbots/", json={"nama_chatbot": "Bot A"})

        assert res.status_code == 422

    async def test_create_invalid_otoritas_returns_422(self, client: AsyncClient):
        """otoritas hanya boleh 'HRD' atau 'Karyawan'."""
        res = await client.post("/api/v1/chatbots/", json=make_payload(otoritas="MANAGER"))

        assert res.status_code == 422

    async def test_create_empty_nama_returns_422(self, client: AsyncClient):
        """nama_chatbot tidak boleh string kosong."""
        res = await client.post("/api/v1/chatbots/", json=make_payload(nama=""))

        assert res.status_code == 422

    async def test_create_nama_stripped_whitespace(self, client: AsyncClient):
        """nama_chatbot dengan spasi di ujung harus di-strip."""
        res = await client.post("/api/v1/chatbots/", json=make_payload(nama="  Stripped Bot  "))

        assert res.status_code == 201
        assert res.json()["nama_chatbot"] == "Stripped Bot"


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/v1/chatbots/
# ══════════════════════════════════════════════════════════════════════════════

class TestListChatbot:

    async def test_list_empty(self, client: AsyncClient):
        """List chatbot saat DB kosong harus return data=[] dan total=0."""
        res = await client.get("/api/v1/chatbots/")

        assert res.status_code == 200
        body = res.json()
        assert body["data"] == []
        assert body["total"] == 0
        assert body["page"] == 1

    async def test_list_returns_all_active(self, client: AsyncClient, db_session: AsyncSession):
        """Semua chatbot aktif harus muncul di list."""
        await seed_chatbot(db_session, nama_chatbot="Bot A")
        await seed_chatbot(db_session, nama_chatbot="Bot B", otoritas=AuthorityEnum.KARYAWAN)

        res = await client.get("/api/v1/chatbots/")

        assert res.json()["total"] == 2

    async def test_list_inactive_included(self, client: AsyncClient, db_session: AsyncSession):
        """Chatbot dengan is_active=False tetap muncul di list default."""
        await seed_chatbot(db_session, nama_chatbot="Aktif Bot")
        await seed_chatbot(db_session, nama_chatbot="Nonaktif Bot", is_active=False)

        res = await client.get("/api/v1/chatbots/")

        body = res.json()
        assert body["total"] == 2
        names = {item["nama_chatbot"] for item in body["data"]}
        assert names == {"Aktif Bot", "Nonaktif Bot"}

    async def test_list_pagination_page_size(self, client: AsyncClient, db_session: AsyncSession):
        """page_size membatasi jumlah item per halaman."""
        for i in range(5):
            await seed_chatbot(db_session, nama_chatbot=f"Bot {i}")

        res = await client.get("/api/v1/chatbots/?page=1&page_size=2")

        body = res.json()
        assert len(body["data"]) == 2
        assert body["total"] == 5
        assert body["total_pages"] == 3

    async def test_list_pagination_page_2_different_items(self, client: AsyncClient, db_session: AsyncSession):
        """Halaman 2 harus return item yang berbeda dari halaman 1."""
        for i in range(4):
            await seed_chatbot(db_session, nama_chatbot=f"Bot {i}")

        res1 = await client.get("/api/v1/chatbots/?page=1&page_size=2")
        res2 = await client.get("/api/v1/chatbots/?page=2&page_size=2")

        ids_page1 = {c["id"] for c in res1.json()["data"]}
        ids_page2 = {c["id"] for c in res2.json()["data"]}
        assert ids_page1.isdisjoint(ids_page2)

    async def test_list_invalid_page_returns_422(self, client: AsyncClient):
        """page < 1 harus return 422."""
        res = await client.get("/api/v1/chatbots/?page=0")

        assert res.status_code == 422

    async def test_list_filter_hrd(self, client: AsyncClient, db_session: AsyncSession):
        """Filter otoritas=HRD hanya return chatbot HRD."""
        await seed_chatbot(db_session, nama_chatbot="HRD Bot", otoritas=AuthorityEnum.HRD)
        await seed_chatbot(db_session, nama_chatbot="Kar Bot", otoritas=AuthorityEnum.KARYAWAN)

        res = await client.get("/api/v1/chatbots/?otoritas=HRD")

        body = res.json()
        assert body["total"] == 1
        assert body["data"][0]["otoritas"] == "HRD"

    async def test_list_filter_karyawan(self, client: AsyncClient, db_session: AsyncSession):
        """Filter otoritas=Karyawan hanya return chatbot Karyawan."""
        await seed_chatbot(db_session, nama_chatbot="HRD Bot", otoritas=AuthorityEnum.HRD)
        await seed_chatbot(db_session, nama_chatbot="Kar Bot", otoritas=AuthorityEnum.KARYAWAN)

        res = await client.get("/api/v1/chatbots/?otoritas=Karyawan")

        body = res.json()
        assert body["total"] == 1
        assert body["data"][0]["otoritas"] == "Karyawan"

    async def test_list_filter_invalid_otoritas_returns_422(self, client: AsyncClient):
        """Filter dengan nilai otoritas tidak valid harus return 422."""
        res = await client.get("/api/v1/chatbots/?otoritas=INVALID")

        assert res.status_code == 422

    async def test_list_search_by_nama(self, client: AsyncClient, db_session: AsyncSession):
        """Search berdasarkan nama_chatbot (partial match)."""
        await seed_chatbot(db_session, nama_chatbot="Recruitment Helper")
        await seed_chatbot(db_session, nama_chatbot="Payroll Bot")

        res = await client.get("/api/v1/chatbots/?search=Recruit")

        assert res.json()["total"] == 1
        assert "Recruitment" in res.json()["data"][0]["nama_chatbot"]

    async def test_list_search_by_addon_prompt(self, client: AsyncClient, db_session: AsyncSession):
        """Search juga mencakup konten addon_prompt."""
        await seed_chatbot(db_session, nama_chatbot="Bot X", addon_prompt="Bantu proses rekrutmen.")
        await seed_chatbot(db_session, nama_chatbot="Bot Y", addon_prompt="Cek gaji.")

        res = await client.get("/api/v1/chatbots/?search=rekrutmen")

        assert res.json()["total"] == 1

    async def test_list_search_no_result(self, client: AsyncClient, db_session: AsyncSession):
        """Search yang tidak cocok harus return data kosong."""
        await seed_chatbot(db_session, nama_chatbot="Bot A")

        res = await client.get("/api/v1/chatbots/?search=xyznotfound")

        assert res.json()["total"] == 0
        assert res.json()["data"] == []


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/v1/chatbots/{id}
# ══════════════════════════════════════════════════════════════════════════════

class TestGetChatbotById:

    async def test_get_by_id_success(self, client: AsyncClient, db_session: AsyncSession):
        """GET /{id} harus return detail chatbot yang benar."""
        chatbot = await seed_chatbot(db_session, nama_chatbot="Detail Bot")

        res = await client.get(f"/api/v1/chatbots/{chatbot.id}")

        assert res.status_code == 200
        data = res.json()
        assert data["id"] == str(chatbot.id)
        assert data["nama_chatbot"] == "Detail Bot"
        assert data["otoritas"] == "HRD"

    async def test_get_by_id_not_found(self, client: AsyncClient):
        """GET dengan ID yang tidak ada harus return 404."""
        res = await client.get("/api/v1/chatbots/45ba7477-99d5-471b-aa4b-9e161c187705")

        assert res.status_code == 404
        assert "tidak ditemukan" in res.json()["detail"]

    async def test_get_inactive_returns_200(self, client: AsyncClient, db_session: AsyncSession):
        """Chatbot nonaktif tetap bisa diakses via GET /{id}."""
        chatbot = await seed_chatbot(db_session, nama_chatbot="Nonaktif Bot", is_active=False)

        res = await client.get(f"/api/v1/chatbots/{chatbot.id}")

        assert res.status_code == 200
        assert res.json()["is_active"] is False

    async def test_get_invalid_id_returns_422(self, client: AsyncClient):
        """ID bukan integer harus return 422."""
        res = await client.get("/api/v1/chatbots/abc")

        assert res.status_code == 422


# ══════════════════════════════════════════════════════════════════════════════
# PATCH /api/v1/chatbots/{id}
# ══════════════════════════════════════════════════════════════════════════════

class TestUpdateChatbot:

    async def test_update_nama_only(self, client: AsyncClient, db_session: AsyncSession):
        """Update hanya nama_chatbot — field lain tidak berubah."""
        chatbot = await seed_chatbot(db_session, nama_chatbot="Lama Bot")

        res = await client.patch(f"/api/v1/chatbots/{chatbot.id}", json={"nama_chatbot": "Baru Bot"})

        assert res.status_code == 200
        data = res.json()
        assert data["nama_chatbot"] == "Baru Bot"
        assert data["otoritas"] == "HRD"  # tidak berubah

    async def test_update_otoritas_only(self, client: AsyncClient, db_session: AsyncSession):
        """Update hanya otoritas — nama tidak berubah."""
        chatbot = await seed_chatbot(db_session, nama_chatbot="Switch Bot")

        res = await client.patch(f"/api/v1/chatbots/{chatbot.id}", json={"otoritas": "Karyawan"})

        assert res.status_code == 200
        data = res.json()
        assert data["otoritas"] == "Karyawan"
        assert data["nama_chatbot"] == "Switch Bot"  # tidak berubah

    async def test_update_addon_prompt(self, client: AsyncClient, db_session: AsyncSession):
        """Update addon_prompt dengan nilai baru."""
        chatbot = await seed_chatbot(db_session, nama_chatbot="Prompt Bot", addon_prompt="Prompt lama.")

        res = await client.patch(f"/api/v1/chatbots/{chatbot.id}", json={"addon_prompt": "Prompt baru."})

        assert res.status_code == 200
        assert res.json()["addon_prompt"] == "Prompt baru."

    async def test_update_addon_prompt_to_null(self, client: AsyncClient, db_session: AsyncSession):
        """addon_prompt bisa di-set ke null."""
        chatbot = await seed_chatbot(db_session, nama_chatbot="Null Prompt Bot", addon_prompt="Ada prompt.")

        res = await client.patch(f"/api/v1/chatbots/{chatbot.id}", json={"addon_prompt": None})

        assert res.status_code == 200
        assert res.json()["addon_prompt"] is None

    async def test_update_all_fields(self, client: AsyncClient, db_session: AsyncSession):
        """Update semua field sekaligus."""
        chatbot = await seed_chatbot(db_session, nama_chatbot="Old Bot")

        res = await client.patch(
            f"/api/v1/chatbots/{chatbot.id}",
            json={"nama_chatbot": "New Bot", "otoritas": "Karyawan",
                  "addon_prompt": "Prompt baru."},
        )

        assert res.status_code == 200
        data = res.json()
        assert data["nama_chatbot"] == "New Bot"
        assert data["otoritas"] == "Karyawan"
        assert data["addon_prompt"] == "Prompt baru."

    async def test_update_is_active_to_false(self, client: AsyncClient, db_session: AsyncSession):
        """is_active bisa di-update melalui PATCH."""
        chatbot = await seed_chatbot(db_session, nama_chatbot="Toggle Bot")

        res = await client.patch(f"/api/v1/chatbots/{chatbot.id}", json={"is_active": False})

        assert res.status_code == 200
        assert res.json()["is_active"] is False

    async def test_update_activate_chatbot_deactivates_other_same_otoritas(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        """Saat aktivasi chatbot, chatbot aktif lain pada otoritas sama harus dinonaktifkan."""
        old_active = await seed_chatbot(
            db_session,
            nama_chatbot="HR Active Lama",
            otoritas=AuthorityEnum.HRD,
            is_active=True,
        )
        to_activate = await seed_chatbot(
            db_session,
            nama_chatbot="HR Active Baru",
            otoritas=AuthorityEnum.HRD,
            is_active=True,
        )

        res = await client.patch(f"/api/v1/chatbots/{to_activate.id}", json={"is_active": True})

        assert res.status_code == 200
        assert res.json()["is_active"] is True

        result = await db_session.execute(
            select(Chatbot).where(Chatbot.id.in_([old_active.id, to_activate.id]))
        )
        chatbots = result.scalars().all()
        for chatbot in chatbots:
            await db_session.refresh(chatbot)
        status_by_id = {str(chatbot.id): chatbot.is_active for chatbot in chatbots}

        assert status_by_id[str(old_active.id)] is False
        assert status_by_id[str(to_activate.id)] is True

    async def test_update_otoritas_active_chatbot_deactivates_active_target_otoritas(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        """Pindah otoritas chatbot aktif harus nonaktifkan chatbot aktif lain di otoritas tujuan."""
        target_active = await seed_chatbot(
            db_session,
            nama_chatbot="Karyawan Active Lama",
            otoritas=AuthorityEnum.KARYAWAN,
            is_active=True,
        )
        mover = await seed_chatbot(
            db_session,
            nama_chatbot="HRD Pindah",
            otoritas=AuthorityEnum.HRD,
            is_active=True,
        )

        res = await client.patch(f"/api/v1/chatbots/{mover.id}", json={"otoritas": "Karyawan"})

        assert res.status_code == 200
        data = res.json()
        assert data["otoritas"] == "Karyawan"
        assert data["is_active"] is True

        result = await db_session.execute(
            select(Chatbot).where(Chatbot.id.in_([target_active.id, mover.id]))
        )
        chatbots = result.scalars().all()
        for chatbot in chatbots:
            await db_session.refresh(chatbot)
        status_by_id = {str(chatbot.id): chatbot.is_active for chatbot in chatbots}

        assert status_by_id[str(target_active.id)] is False
        assert status_by_id[str(mover.id)] is True

    async def test_update_nama_to_existing_returns_409(self, client: AsyncClient, db_session: AsyncSession):
        """Ganti nama ke nama chatbot lain yang sudah ada harus return 409."""
        await seed_chatbot(db_session, nama_chatbot="Existing Bot")
        chatbot2 = await seed_chatbot(db_session, nama_chatbot="Other Bot")

        res = await client.patch(f"/api/v1/chatbots/{chatbot2.id}", json={"nama_chatbot": "Existing Bot"})

        assert res.status_code == 409
        assert "sudah digunakan" in res.json()["detail"]

    async def test_update_same_nama_not_conflict(self, client: AsyncClient, db_session: AsyncSession):
        """Update ke nama yang sama (milik dirinya sendiri) tidak boleh 409."""
        chatbot = await seed_chatbot(db_session, nama_chatbot="Same Name Bot")

        res = await client.patch(f"/api/v1/chatbots/{chatbot.id}", json={"nama_chatbot": "Same Name Bot"})

        assert res.status_code == 200

    async def test_update_not_found_returns_404(self, client: AsyncClient):
        """Update chatbot yang tidak ada harus return 404."""
        res = await client.patch("/api/v1/chatbots/45ba7477-99d5-471b-aa4b-9e161c187705", json={"nama_chatbot": "Ghost Bot"})

        assert res.status_code == 404

    async def test_update_invalid_otoritas_returns_422(self, client: AsyncClient, db_session: AsyncSession):
        """otoritas tidak valid saat update harus return 422."""
        chatbot = await seed_chatbot(db_session, nama_chatbot="Val Bot")

        res = await client.patch(f"/api/v1/chatbots/{chatbot.id}", json={"otoritas": "ADMIN"})

        assert res.status_code == 422

    async def test_update_empty_nama_returns_422(self, client: AsyncClient, db_session: AsyncSession):
        """nama_chatbot tidak boleh string kosong saat update."""
        chatbot = await seed_chatbot(db_session, nama_chatbot="Empty Test Bot")

        res = await client.patch(f"/api/v1/chatbots/{chatbot.id}", json={"nama_chatbot": ""})

        assert res.status_code == 422


# ══════════════════════════════════════════════════════════════════════════════
# DELETE /api/v1/chatbots/{id}  —  Soft Delete
# ══════════════════════════════════════════════════════════════════════════════

class TestSoftDeleteChatbot:

    async def test_soft_delete_returns_200(self, client: AsyncClient, db_session: AsyncSession):
        """Soft delete harus return 200 dengan pesan sukses."""
        chatbot = await seed_chatbot(db_session, nama_chatbot="Soft Del Bot")

        res = await client.delete(f"/api/v1/chatbots/{chatbot.id}")

        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        assert "dinonaktifkan" in body["message"]

    async def test_soft_delete_sets_is_active_false(self, client: AsyncClient, db_session: AsyncSession):
        """Setelah soft delete, is_active di DB harus False."""
        chatbot = await seed_chatbot(db_session, nama_chatbot="Check Active Bot")

        await client.delete(f"/api/v1/chatbots/{chatbot.id}")

        result = await db_session.execute(select(Chatbot).where(Chatbot.id == chatbot.id))
        db_chatbot = result.scalars().first()
        await db_session.refresh(db_chatbot)
        assert db_chatbot is not None
        assert db_chatbot.is_active is False

    async def test_soft_delete_still_accessible_via_get(self, client: AsyncClient, db_session: AsyncSession):
        """Setelah soft delete, GET /{id} tetap bisa diakses dengan status nonaktif."""
        chatbot = await seed_chatbot(db_session, nama_chatbot="Invisible Bot")

        await client.delete(f"/api/v1/chatbots/{chatbot.id}")
        res = await client.get(f"/api/v1/chatbots/{chatbot.id}")

        assert res.status_code == 200
        assert res.json()["is_active"] is False

    async def test_soft_delete_still_in_list(self, client: AsyncClient, db_session: AsyncSession):
        """Setelah soft delete, chatbot tetap muncul di GET / dengan status nonaktif."""
        chatbot = await seed_chatbot(db_session, nama_chatbot="Hidden Bot")

        await client.delete(f"/api/v1/chatbots/{chatbot.id}")
        res = await client.get("/api/v1/chatbots/")

        data_by_id = {c["id"]: c for c in res.json()["data"]}
        assert str(chatbot.id) in data_by_id
        assert data_by_id[str(chatbot.id)]["is_active"] is False

    async def test_soft_delete_not_found_returns_404(self, client: AsyncClient):
        """Soft delete chatbot yang tidak ada harus return 404."""
        res = await client.delete("/api/v1/chatbots/45ba7477-99d5-471b-aa4b-9e161c187705")

        assert res.status_code == 404

    async def test_soft_delete_twice_returns_200(self, client: AsyncClient, db_session: AsyncSession):
        """Soft delete dua kali bersifat idempotent dan tetap return 200."""
        chatbot = await seed_chatbot(db_session, nama_chatbot="Double Del Bot")

        await client.delete(f"/api/v1/chatbots/{chatbot.id}")
        res = await client.delete(f"/api/v1/chatbots/{chatbot.id}")

        assert res.status_code == 200
        assert res.json()["success"] is True


# ══════════════════════════════════════════════════════════════════════════════
# DELETE /api/v1/chatbots/{id}?hard=true  —  Hard Delete
# ══════════════════════════════════════════════════════════════════════════════

class TestHardDeleteChatbot:

    async def test_hard_delete_returns_200(self, client: AsyncClient, db_session: AsyncSession):
        """Hard delete harus return 200 dengan pesan sukses."""
        chatbot = await seed_chatbot(db_session, nama_chatbot="Hard Del Bot")

        res = await client.delete(f"/api/v1/chatbots/{chatbot.id}?hard=true")

        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        assert "permanen" in body["message"]

    async def test_hard_delete_removes_from_db(self, client: AsyncClient, db_session: AsyncSession):
        """Setelah hard delete, record benar-benar hilang dari DB."""
        chatbot = await seed_chatbot(db_session, nama_chatbot="Gone Bot")
        chatbot_id = chatbot.id

        await client.delete(f"/api/v1/chatbots/{chatbot_id}?hard=true")

        result = await db_session.execute(select(Chatbot).where(Chatbot.id == chatbot_id))
        assert result.scalars().first() is None

    async def test_hard_delete_not_found_returns_404(self, client: AsyncClient):
        """Hard delete chatbot yang tidak ada harus return 404."""
        res = await client.delete("/api/v1/chatbots/45ba7477-99d5-471b-aa4b-9e161c187705?hard=true")

        assert res.status_code == 404

    async def test_hard_delete_nama_can_be_reused(self, client: AsyncClient, db_session: AsyncSession):
        """Setelah hard delete, nama yang sama bisa dipakai lagi."""
        chatbot = await seed_chatbot(db_session, nama_chatbot="Reusable Bot")

        await client.delete(f"/api/v1/chatbots/{chatbot.id}?hard=true")
        res = await client.post("/api/v1/chatbots/", json={"nama_chatbot": "Reusable Bot", "otoritas": "HRD"})

        assert res.status_code == 201

    async def test_default_delete_is_soft(self, client: AsyncClient, db_session: AsyncSession):
        """Tanpa ?hard=true, default adalah soft delete — record masih ada di DB."""
        chatbot = await seed_chatbot(db_session, nama_chatbot="Default Del Bot")

        await client.delete(f"/api/v1/chatbots/{chatbot.id}")

        result = await db_session.execute(select(Chatbot).where(Chatbot.id == chatbot.id))
        db_chatbot = result.scalars().first()
        await db_session.refresh(db_chatbot)
        assert db_chatbot is not None        # record masih ada
        assert db_chatbot.is_active is False  # tapi nonaktif
