"""
database.py - Koneksi PostgreSQL dengan SQLAlchemy async
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


from config import settings

# ------------------------------------------------------------------ #
#  Engine & Session                                                    #
# ------------------------------------------------------------------ #

engine = create_async_engine(
    settings.DATABASE_URL,
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

async def get_db() -> AsyncSession:  # type: ignore
    async with AsyncSessionLocal() as session:
        yield session


async def create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
