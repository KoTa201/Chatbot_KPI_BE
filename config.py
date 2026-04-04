class Settings:
    DATABASE_URL = "postgresql+asyncpg://postgres:secret@localhost:5432/chatbot_kpi"
    GOOGLE_CREDENTIALS_PATH = "chatbotkpi-491800-2ff5e01549b5.json"
    APP_ENV = "development"
    SECRET_KEY = "daffa-kampret-123"
    ACCESS_TOKEN_EXPIRE_MINUTES = 60
    # secret terpisah, bukan SECRET_KEY yang sama
    REFRESH_SECRET_KEY = "chatbot-kpi-amani-123"
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7


settings = Settings()
