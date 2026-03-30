"""
FastAPI - Structured RAG Ingestion KPI Tracker
- Autentikasi Google Sheets via Service Account
- Penyimpanan ke PostgreSQL
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
import model
from databaseConfig import create_tables
from router import ingestionRouter as ingestion, recordRouter as records, userRouter as users
from fastapi.middleware.cors import CORSMiddleware
from middleware.jwtMiddleware import JWTMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Buat tabel PostgreSQL saat startup jika belum ada
    await create_tables()
    yield


app = FastAPI(
    title="KPI RAG Ingestion API",
    description=(
        "Ingestion structured RAG dari Google Sheets via Service Account. "
        "Data disimpan ke PostgreSQL."
    ),
    version="3.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # sesuaikan dengan kebutuhan production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(JWTMiddleware)  # dieksekusi pertama sebelum router

app.include_router(ingestion.router, prefix="/ingest", tags=["Ingestion"])
app.include_router(records.router, prefix="/records", tags=["Records"])
app.include_router(users.router, prefix="/users", tags=["Users"])


@app.get("/", tags=["Health"])
async def root():
    return {"status": "ok", "service": "KPI RAG Ingestion API v3"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
