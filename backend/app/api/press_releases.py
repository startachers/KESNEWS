from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from backend.app.api.envelope import error_response, ok_envelope
from backend.app.repositories import press_release_repository as press_release_repo
from backend.app.repositories.database import get_connection
from backend.app.services.collection.kesco_press_cache import (
    get_kesco_press_cache_status,
    refresh_kesco_press_cache,
)

logger = logging.getLogger("kesco.press_releases")
router = APIRouter()


class PressReleaseRefreshRequest(BaseModel):
    maxRecords: int = Field(default=30, ge=10, le=100)


@router.get("/api/kesco-press-releases/status")
async def press_release_status() -> dict[str, Any]:
    data = await asyncio.to_thread(get_kesco_press_cache_status)
    return ok_envelope(data)


@router.get("/api/kesco-press-releases")
async def list_press_releases(limit: int = Query(default=30, ge=1, le=100)) -> dict[str, Any]:
    connection = get_connection()
    try:
        releases = press_release_repo.list_recent(connection, limit)
    finally:
        connection.close()
    return ok_envelope({"pressReleases": releases, "count": len(releases)})


@router.post("/api/kesco-press-releases/refresh")
async def refresh_press_releases(request: PressReleaseRefreshRequest) -> dict[str, Any]:
    try:
        data = await refresh_kesco_press_cache(request.maxRecords)
    except Exception:
        logger.exception("KESCO 보도자료 원문 갱신 실패")
        return error_response(
            "KESCO_PRESS_REFRESH_FAILED",
            "공사 보도자료를 가져오지 못했습니다. 기존 저장 원문은 유지됩니다.",
        )
    return ok_envelope(data)
