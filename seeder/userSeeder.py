"""
seeders/user_seeder.py
Seeder untuk mengisi tabel users dengan data awal.
- 2 admin
- 3 user biasa

Jalankan:
    python -m seeders.user_seeder

Seeder bersifat idempoten: user yang sudah ada (by username) dilewati,
tidak akan duplikat meskipun dijalankan berkali-kali.
"""

from model.User import RoleEnum, UserORM
from databaseConfig import get_db
from sqlalchemy import select
import bcrypt
import asyncio
import sys
from pathlib import Path

# Pastikan root project masuk ke sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent))


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
    {
        "username": "admin_budi",
        "email": "budi.admin@kpiapp.id",
        "full_name": "Budi Santoso",
        "password": "Admin123",
        "role": RoleEnum.admin,
        "is_active": True,
    },
    # ── User biasa ─────────────────────────────────────────────────
    {
        "username": "pirmadi",
        "email": "pirmadi@kpiapp.id",
        "full_name": "Pirmadi Surya",
        "password": "User1234",
        "role": RoleEnum.user,
        "is_active": True,
    },
    {
        "username": "siti_rahayu",
        "email": "siti.rahayu@kpiapp.id",
        "full_name": "Siti Rahayu",
        "password": "User1234",
        "role": RoleEnum.user,
        "is_active": True,
    },
    {
        "username": "Daiva",
        "email": "daivaraditya36@gmail.com",
        "full_name": "Rizky Pratama",
        "password": "User1234",
        "role": RoleEnum.user,
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
                select(UserORM).where(UserORM.username == data["username"])
            )
            existing = result.scalar_one_or_none()

            if existing:
                print(f"  [SKIP]   {data['username']:<20} (sudah ada)")
                skipped += 1
                continue

            user = UserORM(
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
    print(f"  {'-'*20} {'-'*12} {'-'*10}")
    for u in SEED_USERS:
        print(f"  {u['username']:<20} {u['password']:<12} {u['role'].value}")
    print()


if __name__ == "__main__":
    asyncio.run(run_seeder())
