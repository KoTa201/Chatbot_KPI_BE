from dotenv import load_dotenv
import os

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


settings = Settings()
