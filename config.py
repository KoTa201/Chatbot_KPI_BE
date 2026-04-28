from dotenv import load_dotenv
import os
from functools import lru_cache

# Load environment variables from .env file
load_dotenv()


class Settings:
    DATABASE_URL = os.getenv("DATABASE_URL")
    GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH")
    APP_ENV = os.getenv("APP_ENV")
    SECRET_KEY = os.getenv("SECRET_KEY")
    ACCESS_TOKEN_EXPIRE_MINUTES = int(
        os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES") or 60)
    REFRESH_SECRET_KEY = os.getenv("REFRESH_SECRET_KEY")
    REFRESH_TOKEN_EXPIRE_DAYS = int(
        os.getenv("REFRESH_TOKEN_EXPIRE_DAYS") or 7)
    RESET_SECRET_KEY: str = os.getenv("RESET_SECRET_KEY")
    SMTP_FROM: str = os.getenv("SMTP_FROM")
    SMTP_HOST: str = os.getenv("SMTP_HOST")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT") or 587)
    SMTP_USER: str = os.getenv("SMTP_USER")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD")
    # LLM Configuration
    LLM_API_KEY: str = (
        os.getenv("LLM_MODEL_API_KEY")
    )
    LLM_BASE_URL: str = (
        os.getenv("LLM_MODEL_BASE_URl")
    )
    LLM_MODEL_NL_TO_SQL: str = (
        os.getenv("LLM_MODEL_NL_TO_SQL")
    )
    LLM_MODEL_ANALYSIS: str = (
        os.getenv("LLM_MODEL_ANALYSIS")
    )
    LLM_MODEL_GRAPHIC_CLASSIFIER: str = (
        os.getenv("LLM_MODEL_GRAPHIC_CLASSIFIER")
    )
    LLM_MODEL_DISAMBIGUATION: str = (
        os.getenv("LLM_MODEL_DISAMBIGUATION")
    )
    RATE_LIMIT_PER_MINUTE: int = int(os.getenv("RATE_LIMIT_PER_MINUTE") or 30)
    SQL_MAX_LIMIT: int = int(os.getenv("SQL_MAX_LIMIT") or 5000)
    SQL_MAX_SUBQUERY_DEPTH: int = int(os.getenv("SQL_MAX_SUBQUERY_DEPTH") or 3)
    SQL_EXECUTION_TIMEOUT: int = int(os.getenv("SQL_EXECUTION_TIMEOUT") or 30)
    CORS_ORIGINS: str = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
    CORS_ORIGIN_REGEX: str = os.getenv(
        "CORS_ORIGIN_REGEX",
        r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    )


settings = Settings()


@lru_cache()
def get_settings() -> Settings:
    return Settings()
