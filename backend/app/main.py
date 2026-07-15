from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend.app.api.articles import router as articles_router
from backend.app.api.analysis import router as analysis_router
from backend.app.api.briefings import router as briefings_router
from backend.app.api.collections import router as collections_router
from backend.app.api.exports import router as exports_router
from backend.app.api.issues import router as issues_router
from backend.app.api.reports import router as reports_router
from backend.app.repositories.database import get_connection, init_db
from backend.app.services.ai.ollama_client import OllamaError, default_client

BASE_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = BASE_DIR / "frontend"
LOG_DIR = BASE_DIR / "logs"

LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "app.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("kesco.app")

app = FastAPI(title="KESCO Media Briefing")


@app.on_event("startup")
async def _run_migrations_on_startup() -> None:
    applied_migrations = await asyncio.to_thread(init_db)
    if applied_migrations:
        logger.info("DB migration 적용: %s", ", ".join(applied_migrations))


def _check_db_connected() -> bool:
    try:
        connection = get_connection()
        try:
            connection.execute("SELECT 1")
            return True
        finally:
            connection.close()
    except OSError:
        return False


def _fetch_ollama_tags() -> tuple[list[dict], str, str | None]:
    """Ollama는 선택 의존성이다. 실패해도 /api/health 자체는 정상으로 응답한다."""
    try:
        models = default_client.list_models()
    except OllamaError as exc:
        logger.info("Ollama 조회 실패, models=[]로 응답: %s", exc)
        return [], "", str(exc)

    default_model = models[0].get("name", "") if models else ""
    return models, default_model, None


@app.get("/api/health")
async def health() -> dict:
    models, default_model, ollama_error = await asyncio.to_thread(_fetch_ollama_tags)
    db_connected = await asyncio.to_thread(_check_db_connected)
    return {"ok": True, "models": models, "defaultModel": default_model, "dbConnected": db_connected, "error": ollama_error}


app.include_router(collections_router)
app.include_router(analysis_router)
app.include_router(articles_router)
app.include_router(briefings_router)
app.include_router(exports_router)
app.include_router(issues_router)
app.include_router(reports_router)
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
