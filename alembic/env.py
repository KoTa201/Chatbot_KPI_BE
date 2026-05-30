from model.Base import Base
from logging.config import fileConfig
from sqlalchemy import create_engine, pool, text
from alembic import context
from dotenv import load_dotenv
import os
import sys

# path setup
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# load env
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise Exception("DATABASE_URL not found in .env")

# pakai driver sync
DATABASE_URL = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")

# config alembic
config = context.config
config.set_main_option("sqlalchemy.url", DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# metadata
target_metadata = Base.metadata


def run_migrations_offline():
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
    )

    context.run_migrations()


def run_migrations_online():
    engine = create_engine(
        DATABASE_URL,
        poolclass=pool.NullPool,
    )

    with engine.connect() as connection:
        print(">>> CONNECTED TO:", connection.execute(
            text("SELECT current_database()")
        ).scalar())

    with engine.begin() as connection:
        print(">>> CONNECTED TO:", connection.execute(
            text("SELECT current_database()")
        ).scalar())

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
