"""
seeders/user_seeder.py
Seeder untuk mengisi tabel users dengan data awal.
- 1 admin
- 3 kepala_divisi
- 3 karyawan (default)
- 17 karyawan (dari KPI Master 2025 — responsibility_persons)

Jalankan:
    python -m seeders.user_seeder

Seeder bersifat idempoten: user yang sudah ada (by username) dilewati,
tidak akan duplikat meskipun dijalankan berkali-kali.
"""

import asyncio
import sys
from pathlib import Path

import bcrypt
from sqlalchemy import select

# Pastikan root project masuk ke sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from model.User import RoleEnum, User
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
    # ── Karyawan (default) ─────────────────────────────────────────
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
    # ── Karyawan (KPI Master 2025 — Responsibility Persons) ────────
    {
        "username": "pirmadi",
        "email": "pirmadi@kpiapp.id",
        "full_name": "Pirmadi S",          # KPI: High Level
        "password": "User1234",
        "role": RoleEnum.karyawan,
        "is_active": True,
    },
    {
        "username": "djoko_k",
        "email": "djoko.k@kpiapp.id",
        "full_name": "Djoko K",            # KPI: High Level, Project Delivery
        "password": "User1234",
        "role": RoleEnum.karyawan,
        "is_active": True,
    },
    {
        "username": "erlan_h",
        "email": "erlan.h@kpiapp.id",
        "full_name": "Erlan H",            # KPI: Product Management
        "password": "User1234",
        "role": RoleEnum.karyawan,
        "is_active": True,
    },
    {
        "username": "farhan",
        "email": "farhan@kpiapp.id",
        "full_name": "Farhan",             # KPI: Product Management
        "password": "User1234",
        "role": RoleEnum.karyawan,
        "is_active": True,
    },
    {
        "username": "andi",
        "email": "andi@kpiapp.id",
        "full_name": "Andi",               # KPI: Product Management
        "password": "User1234",
        "role": RoleEnum.karyawan,
        "is_active": True,
    },
    {
        "username": "adiansyah",
        "email": "adiansyah@kpiapp.id",
        "full_name": "Adiansyah",          # KPI: Product Management
        "password": "User1234",
        "role": RoleEnum.karyawan,
        "is_active": True,
    },
    {
        "username": "bandy",
        "email": "bandy@kpiapp.id",
        "full_name": "Bandy",              # KPI: Project Delivery
        "password": "User1234",
        "role": RoleEnum.karyawan,
        "is_active": True,
    },
    {
        "username": "rafly",
        "email": "rafly@kpiapp.id",
        "full_name": "Rafly",              # KPI: Project Delivery
        "password": "User1234",
        "role": RoleEnum.karyawan,
        "is_active": True,
    },
    {
        "username": "akmal",
        "email": "akmal@kpiapp.id",
        "full_name": "Akmal",              # KPI: Project Delivery
        "password": "User1234",
        "role": RoleEnum.karyawan,
        "is_active": True,
    },
    {
        "username": "mia",
        "email": "mia@kpiapp.id",
        "full_name": "Mia",                # KPI: Pre-Sales/Sales Support
        "password": "User1234",
        "role": RoleEnum.karyawan,
        "is_active": True,
    },
    {
        "username": "dini",
        "email": "dini@kpiapp.id",
        "full_name": "Dini",               # KPI: Pre-Sales/Sales Support
        "password": "User1234",
        "role": RoleEnum.karyawan,
        "is_active": True,
    },
    {
        "username": "jessica",
        "email": "jessica@kpiapp.id",
        "full_name": "Jessica",            # KPI: Pre-Sales/Sales Support
        "password": "User1234",
        "role": RoleEnum.karyawan,
        "is_active": True,
    },
    {
        "username": "abdul_r",
        "email": "abdul.r@kpiapp.id",
        "full_name": "Abdul R",            # KPI: Partner/Subcon Handling
        "password": "User1234",
        "role": RoleEnum.karyawan,
        "is_active": True,
    },
    {
        "username": "tresna",
        "email": "tresna@kpiapp.id",
        "full_name": "Tresna",             # KPI: Partner/Subcon Handling
        "password": "User1234",
        "role": RoleEnum.karyawan,
        "is_active": True,
    },
    {
        "username": "hasbi",
        "email": "hasbi@kpiapp.id",
        "full_name": "Hasbi",              # KPI: Partner/Subcon Handling
        "password": "User1234",
        "role": RoleEnum.karyawan,
        "is_active": True,
    },
    {
        "username": "heri",
        "email": "heri@kpiapp.id",
        "full_name": "Heri",               # KPI: Team Growth
        "password": "User1234",
        "role": RoleEnum.karyawan,
        "is_active": True,
    },
    {
        "username": "romli",
        "email": "romli@kpiapp.id",
        "full_name": "Romli",              # KPI: Team Growth
        "password": "User1234",
        "role": RoleEnum.karyawan,
        "is_active": True,
    },
    {
        "username": "dani",
        "email": "dani@kpiapp.id",
        "full_name": "Dani",               # KPI: Team Growth
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