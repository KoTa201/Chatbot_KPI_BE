"""
seeders/user_seeder.py
Seeder untuk mengisi tabel users dengan data awal.
- 1 admin
- 3 kepala_divisi
- 3 karyawan

Jalankan:
    python -m seeders.user_seeder

Seeder bersifat idempoten: user yang sudah ada (by username) dilewati,
tidak akan duplikat meskipun dijalankan berkali-kali.
"""

from model.User import RoleEnum, User
from databaseConfig import get_db
from sqlalchemy import select
import bcrypt
import asyncio
import sys
from pathlib import Path
import asyncio

import bcrypt
from sqlalchemy import select

# Pastikan root project masuk ke sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from model.User import RoleEnum, UserORM
from databaseConfig import get_db


# ------------------------------------------------------------------ #
#  Helper hash (tanpa passlib)                                         #
# ------------------------------------------------------------------ #

def _hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


# ------------------------------------------------------------------ #
#  Data seed                                                           #
# ------------------------------------------------------------------ #

SEED_USERS = [
    # ── Admin ──────────────────────────────────────────────────────
    {
        "username": "superadmin",
        "email": "superadmin@kpiapp.id",
        "full_name": "Super Administrator",
        "password": "Admin123",
        "role": RoleEnum.admin,
        "is_active": True,
    },
    # ── Kepala Divisi ───────────────────────────────────────────────
    {
        "username": "kadiv_rina",
        "email": "rina.kadiv@kpiapp.id",
        "full_name": "Rina Marlina",
        "password": "Hrd12345",
        "role": RoleEnum.kepala_divisi,
        "is_active": True,
    },
    {
        "username": "kadiv_budi",
        "email": "budi.kadiv@kpiapp.id",
        "full_name": "Budi Santoso",
        "password": "Kadiv123",
        "role": RoleEnum.kepala_divisi,
        "is_active": True,
    },
    {
        "username": "kadiv_sari",
        "email": "sari.kadiv@kpiapp.id",
        
        "full_name": "Sari Dewi",
        "password": "Kadiv123",
        "role": RoleEnum.kepala_divisi,
        "is_active": True,
    },
    # ── Karyawan ───────────────────────────────────────────────────
    {
        "username": "pirmadi",
        "email": "pirmadi@kpiapp.id",
        "full_name": "Pirmadi Surya",
        "password": "User1234",
        "role": RoleEnum.karyawan,
        "is_active": True,
    },
    {
        "username": "siti_rahayu",
        "email": "siti.rahayu@kpiapp.id",
        "full_name": "Siti Rahayu",
        "password": "User1234",
        "role": RoleEnum.karyawan,
        "is_active": True,
    },
    {
        "username": "Daiva",
        "email": "daivaraditya36@gmail.com",
        "full_name": "Rizky Pratama",
        "password": "User1234",
        "role": RoleEnum.karyawan,
        "is_active": True,
    },
]


# ------------------------------------------------------------------ #
#  Runner                                                              #
# ------------------------------------------------------------------ #

async def run_seeder() -> None:
    print("=" * 55)
    print("  USER SEEDER")
    print("=" * 55)

    inserted = 0
    skipped = 0

    async for db in get_db():
        for data in SEED_USERS:
            # Cek apakah username sudah ada (idempoten)
            result = await db.execute(
                select(User).where(User.username == data["username"])
            )
            existing = result.scalar_one_or_none()

            if existing:
                print(f"  [SKIP]   {data['username']:<20} (sudah ada)")
                skipped += 1
                continue

            user = User(
                username=data["username"],
                email=data["email"],
                full_name=data["full_name"],
                hashed_password=_hash_password(data["password"]),
                role=data["role"],
                is_active=data["is_active"],
            )
            db.add(user)
            print(
                f"  [INSERT] {data['username']:<20} role={data['role'].value}")
            inserted += 1

        await db.commit()

    print("-" * 55)
    print(f"  Selesai — inserted: {inserted}, skipped: {skipped}")
    print("=" * 55)
    print()
    print("  Credential login:")
    print()
    print(f"  {'USERNAME':<20} {'PASSWORD':<12} {'ROLE'}")
    print(f"  {'-'*20} {'-'*12} {'-'*15}")
    for u in SEED_USERS:
        print(f"  {u['username']:<20} {u['password']:<12} {u['role'].value}")
    print()


if __name__ == "__main__":
    asyncio.run(run_seeder())
