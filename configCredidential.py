from dotenv import load_dotenv
import os
from functools import lru_cache

# Load environment variables from .env file
load_dotenv()


def get_required_env(key: str) -> str:
    value = os.getenv(key)
    if value is None:
        raise RuntimeError(f"Missing required environment variable: {key}")
    return value


def get_required_int_env(key: str) -> int:
    return int(get_required_env(key))


class Settings:
    DATABASE_URL: str = get_required_env("DATABASE_URL")
    GOOGLE_CREDENTIALS_PATH: str = get_required_env("GOOGLE_CREDENTIALS_PATH")
    APP_ENV: str = get_required_env("APP_ENV")
    SECRET_KEY: str = get_required_env("SECRET_KEY")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = get_required_int_env(
        "ACCESS_TOKEN_EXPIRE_MINUTES")
    REFRESH_SECRET_KEY: str = get_required_env("REFRESH_SECRET_KEY")
    REFRESH_TOKEN_EXPIRE_DAYS: int = get_required_int_env(
        "REFRESH_TOKEN_EXPIRE_DAYS")
    RESET_SECRET_KEY: str = get_required_env("RESET_SECRET_KEY")
    AUTH_ALGORITHM: str = get_required_env("AUTH_ALGORITHM")
    AUTH_TOKEN_TYPE: str = get_required_env("AUTH_TOKEN_TYPE")
    AUTH_REFRESH_TOKEN_TYPE: str = get_required_env("AUTH_REFRESH_TOKEN_TYPE")
    AUTH_RESET_TOKEN_TYPE: str = get_required_env("AUTH_RESET_TOKEN_TYPE")
    AUTH_PIN_EXPIRE_MINUTES: int = get_required_int_env(
        "AUTH_PIN_EXPIRE_MINUTES")
    AUTH_RESET_TOKEN_EXPIRE_MINUTES: int = get_required_int_env(
        "AUTH_RESET_TOKEN_EXPIRE_MINUTES")
    SMTP_FROM: str = get_required_env("SMTP_FROM")
    SMTP_HOST: str = get_required_env("SMTP_HOST")
    SMTP_PORT: int = get_required_int_env("SMTP_PORT")
    SMTP_USER: str = get_required_env("SMTP_USER")
    SMTP_PASSWORD: str = get_required_env("SMTP_PASSWORD")
    # LLM Configuration
    LLM_API_KEY: str = get_required_env("LLM_MODEL_API_KEY")
    LLM_BASE_URL: str = get_required_env("LLM_MODEL_BASE_URL")
    LLM_MODEL_NL_TO_SQL: str = get_required_env("LLM_MODEL_NL_TO_SQL")
    LLM_MODEL_ANALYSIS: str = get_required_env("LLM_MODEL_ANALYSIS")
    LLM_MODEL_GRAPHIC_CLASSIFIER: str = get_required_env(
        "LLM_MODEL_GRAPHIC_CLASSIFIER")
    LLM_MODEL_DISAMBIGUATION: str = get_required_env(
        "LLM_MODEL_DISAMBIGUATION")
    RATE_LIMIT_PER_MINUTE: int = get_required_int_env("RATE_LIMIT_PER_MINUTE")
    SQL_MAX_LIMIT: int = get_required_int_env("SQL_MAX_LIMIT")
    SQL_MAX_SUBQUERY_DEPTH: int = get_required_int_env("SQL_MAX_SUBQUERY_DEPTH")
    SQL_EXECUTION_TIMEOUT: int = get_required_int_env("SQL_EXECUTION_TIMEOUT")
    CORS_ORIGINS: str = get_required_env("CORS_ORIGINS")
    CORS_ORIGIN_REGEX: str = get_required_env("CORS_ORIGIN_REGEX")


settings = Settings()


@lru_cache()
def get_settings() -> Settings:
    return Settings()
