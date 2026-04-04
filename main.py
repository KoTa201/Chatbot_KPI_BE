"""
FastAPI - Structured RAG Ingestion KPI Tracker
- Autentikasi Google Sheets via Service Account
- Penyimpanan ke PostgreSQL
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
import model
from databaseConfig import create_tables
from router import (
    ingestionRouter as ingestion,
    recordRouter as records,
    userRouter as users,
    chatbotRouter as chatbot_router,
    kpiMasterRouter as kpi_master,
    schedulerRouter as scheduler_router,
)
from fastapi.middleware.cors import CORSMiddleware
from middleware.jwtMiddleware import JWTMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_tables()
    from service.schedulerService import scheduler, register_job
    from repository.schedulerRepository import SchedulerRepository
    from databaseConfig import AsyncSessionLocal
    scheduler.start()
    async with AsyncSessionLocal() as db:
        repo = SchedulerRepository(db)
        config = await repo.get_config()
        if config and config.is_enabled:
            await register_job(config)
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(
    title="KPI RAG Ingestion API",
    description=(
        "Ingestion structured RAG dari Google Sheets via Service Account. "
        "Data disimpan ke PostgreSQL."
    ),
    version="3.0.0",
    lifespan=lifespan,
)

app.add_middleware(JWTMiddleware)  # dieksekusi pertama sebelum router

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # sesuaikan dengan kebutuhan production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(
    ingestion.router, prefix="/api/v1/ingest", tags=["Ingestion"])
app.include_router(records.router, prefix="/api/v1/records", tags=["Records"])
app.include_router(users.router, prefix="/api/v1/users", tags=["Users"])
app.include_router(
    chatbot_router.router, prefix="/api/v1/chatbots", tags=["Chatbots"])
app.include_router(
    kpi_master.router, prefix="/api/v1/ingest/kpi-master", tags=["KPI Master"])
app.include_router(
    scheduler_router.router, prefix="/api/v1/scheduler", tags=["Scheduler"])


@app.get("/", tags=["Health"])
async def root():
    return {"status": "ok", "service": "KPI RAG Ingestion API v3"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
