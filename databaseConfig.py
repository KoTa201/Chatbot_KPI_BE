"""
database.py - Koneksi PostgreSQL dengan SQLAlchemy async
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from typing import AsyncGenerator


from config import settings


def _normalize_async_database_url(db_url: str | None) -> str:
    if not db_url:
        raise ValueError("DATABASE_URL is not set")

    # SQLAlchemy async engine must use an async driver (e.g. asyncpg).
    if db_url.startswith("postgresql+psycopg2://"):
        return db_url.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
    if db_url.startswith("postgresql://"):
        return db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if db_url.startswith("postgres://"):
        return db_url.replace("postgres://", "postgresql+asyncpg://", 1)

    return db_url

# ------------------------------------------------------------------ #
#  Engine & Session                                                    #
# ------------------------------------------------------------------ #


engine = create_async_engine(
    _normalize_async_database_url(settings.DATABASE_URL),
    connect_args={"server_settings": {"search_path": "public"}},
    echo=False,
    pool_size=10,
    max_overflow=20,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# ------------------------------------------------------------------ #
#  Base Model                                                          #
# ------------------------------------------------------------------ #

class Base(DeclarativeBase):
    pass


# ------------------------------------------------------------------ #
#  Dependency                                                          #
# ------------------------------------------------------------------ #

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
