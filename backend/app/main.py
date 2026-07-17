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
from backend.app.api.article_selection import router as article_selection_router
from backend.app.api.briefings import router as briefings_router
from backend.app.api.collections import router as collections_router
from backend.app.api.exports import router as exports_router
from backend.app.api.issues import router as issues_router
from backend.app.api.operations import router as operations_router
from backend.app.api.press_releases import router as press_releases_router
from backend.app.api.reports import router as reports_router
from backend.app.api.report_drafts import router as report_drafts_router
from backend.app.core.logging import configure_logging
from backend.app.repositories.database import check_database_integrity, get_connection, init_db
from backend.app.repositories import ai_run_repository as ai_runs_repo
from backend.app.repositories import ai_selection_repository as ai_selection_repo
from backend.app.services.ai.ollama_client import OllamaError, default_client
from backend.app.services.collection.kesco_press_cache import refresh_kesco_press_cache

BASE_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = BASE_DIR / "frontend"
configure_logging()
logger = logging.getLogger("kesco.app")
SERVICE_ID = "kesco-media-briefing"
INSTANCE_ID = f"{os.getpid()}-{uuid4().hex[:8]}"

app = FastAPI(title="KESCO Media Briefing")


@app.middleware("http")
async def _disable_frontend_asset_cache(request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.endswith((".html", ".js", ".css")):
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


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
            recovered += ai_selection_repo.fail_running(
                connection, "AI_INTERRUPTED: 앱 재시작으로 기사 추천이 중단됐습니다."
            )
        if recovered:
            logger.warning("미완료 AI 실행 %s건을 중단 상태로 복구했습니다.", recovered)
    finally:
        connection.close()
    if os.environ.get("KESCO_PRESS_REFRESH_ON_STARTUP", "1") != "0":
        app.state.kesco_press_refresh_task = asyncio.create_task(
            _refresh_kesco_press_on_startup()
        )


async def _refresh_kesco_press_on_startup() -> None:
    try:
        result = await refresh_kesco_press_cache(30)
        logger.info(
            "KESCO 보도자료 원문 갱신: 신규 조회 %s건, 저장 %s건",
            result["refreshedCount"],
            result["releaseCount"],
        )
    except Exception:
        logger.warning(
            "KESCO 보도자료 시작 갱신 실패, 기존 저장 원문을 사용합니다.",
            exc_info=True,
        )


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

    names = [str(model.get("name") or "") for model in models]
    default_model = next(
        (name for name in names if name.lower() == "gemma4:31b"),
        names[0] if names else "",
    )
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
app.include_router(press_releases_router)
app.include_router(analysis_router)
app.include_router(article_selection_router)
app.include_router(articles_router)
app.include_router(briefings_router)
app.include_router(exports_router)
app.include_router(issues_router)
app.include_router(reports_router)
app.include_router(report_drafts_router)
app.include_router(operations_router)
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
