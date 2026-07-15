from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend.app.api.articles import router as articles_router
from backend.app.api.analysis import router as analysis_router
from backend.app.api.briefings import router as briefings_router
from backend.app.api.collections import router as collections_router
from backend.app.api.exports import router as exports_router
from backend.app.api.issues import router as issues_router
from backend.app.api.operations import router as operations_router
from backend.app.api.reports import router as reports_router
from backend.app.core.logging import configure_logging
from backend.app.repositories.database import check_database_integrity, get_connection, init_db
from backend.app.repositories import ai_run_repository as ai_runs_repo
from backend.app.services.ai.ollama_client import OllamaError, default_client

BASE_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = BASE_DIR / "frontend"
configure_logging()
logger = logging.getLogger("kesco.app")
SERVICE_ID = "kesco-media-briefing"
INSTANCE_ID = f"{os.getpid()}-{uuid4().hex[:8]}"

app = FastAPI(title="KESCO Media Briefing")


@app.on_event("startup")
async def _run_migrations_on_startup() -> None:
    applied_migrations = await asyncio.to_thread(init_db)
    if applied_migrations:
        logger.info("DB migration 적용: %s", ", ".join(applied_migrations))
    connection = get_connection()
    try:
        with connection:
            recovered = ai_runs_repo.fail_running(
                connection, "AI_INTERRUPTED: 앱 재시작으로 실행이 중단됐습니다."
            )
        if recovered:
            logger.warning("미완료 AI 실행 %s건을 중단 상태로 복구했습니다.", recovered)
    finally:
        connection.close()


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


def _check_db_health() -> tuple[bool, str]:
    try:
        return check_database_integrity()
    except OSError as exc:
        return False, str(exc)


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
    db_integrity, _ = await asyncio.to_thread(_check_db_health)
    return {
        "ok": True,
        "service": SERVICE_ID,
        "instanceId": INSTANCE_ID,
        "models": models,
        "defaultModel": default_model,
        "dbConnected": db_connected,
        "dbIntegrity": db_integrity,
        "error": ollama_error,
    }


app.include_router(collections_router)
app.include_router(analysis_router)
app.include_router(articles_router)
app.include_router(briefings_router)
app.include_router(exports_router)
app.include_router(issues_router)
app.include_router(reports_router)
app.include_router(operations_router)
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
