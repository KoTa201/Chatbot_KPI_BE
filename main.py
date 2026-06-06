"""
FastAPI - Structured RAG Ingestion KPI Tracker
- Autentikasi Google Sheets via Service Account
- Penyimpanan ke PostgreSQL
"""

from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import model
from databaseConfig import create_tables
from configCredidential import settings
from router import (
    kpiTrackerRouter as ingestion,
    userRouter as users,
    chatbotRouter as chatbot_router,
    kpiMasterRouter as kpi_master,
    schedulerRouter as scheduler_router,
    kpiGroupRouter as kpi_group_router,
    chatRouter as chat_router,
)
from fastapi.middleware.cors import CORSMiddleware
from middleware.jwtMiddleware import JWTMiddleware
from service.schedulerJobService import scheduler_job_service
from repository.schedulerRepository import SchedulerRepository


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler_job_service.start()
    repo = SchedulerRepository()
    config = await repo.get_config()
    if config.is_enabled:
        scheduler_job_service.register_job(config)
    yield
    scheduler_job_service.stop()


app = FastAPI(
    title="KPI RAG Ingestion API",
    description=(
        "Ingestion structured RAG dari Google Sheets via Service Account. "
        "Data disimpan ke PostgreSQL."
    ),
    version="3.0.0",
    lifespan=lifespan,
)

PUBLIC_DIR = Path("public")
PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/public", StaticFiles(directory=PUBLIC_DIR), name="public")

app.add_middleware(JWTMiddleware)


cors_origins = [origin.strip() for origin in settings.CORS_ORIGINS.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_origin_regex=settings.CORS_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(
    ingestion.router, prefix="/api/v1/ingest", tags=["Ingestion"])
app.include_router(users.router, prefix="/api/v1/users", tags=["Users"])
app.include_router(
    chatbot_router.router, prefix="/api/v1/chatbots", tags=["Chatbots"])
app.include_router(
    kpi_master.router, prefix="/api/v1/ingest/kpi-master", tags=["KPI Master"])
app.include_router(
    scheduler_router.router, prefix="/api/v1/scheduler", tags=["Scheduler"])
app.include_router(
    kpi_group_router.router, prefix="/api/v1/kpi", tags=["KPI Groups"])
app.include_router(chat_router.router,
                   prefix="/api/v1/chat", tags=["Chatbot KPI"])


@app.get("/", tags=["Health"])
async def root():
    return {"status": "ok", "service": "KPI RAG Ingestion API v3"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
