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
    AUTH_ALGORITHM: str = os.getenv("AUTH_ALGORITHM") or "HS256"
    AUTH_TOKEN_TYPE: str = os.getenv("AUTH_TOKEN_TYPE") or "bearer"
    AUTH_REFRESH_TOKEN_TYPE: str = os.getenv(
        "AUTH_REFRESH_TOKEN_TYPE") or "refresh"
    AUTH_RESET_TOKEN_TYPE: str = os.getenv(
        "AUTH_RESET_TOKEN_TYPE") or "reset"
    AUTH_PIN_EXPIRE_MINUTES: int = int(
        os.getenv("AUTH_PIN_EXPIRE_MINUTES") or 15)
    AUTH_RESET_TOKEN_EXPIRE_MINUTES: int = int(
        os.getenv("AUTH_RESET_TOKEN_EXPIRE_MINUTES") or 10)
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


settings = Settings()


@lru_cache()
def get_settings() -> Settings:
    return Settings()
