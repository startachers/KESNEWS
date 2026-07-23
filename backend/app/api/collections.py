from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from fastapi import APIRouter, Query
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from backend.app.api.envelope import error_response, ok_envelope
from backend.app.repositories import dropped_article_repository as dropped_repo
from backend.app.repositories import run_repository as run_repo
from backend.app.repositories.database import get_connection
from backend.app.services.collection.collector import run_collection
from backend.app.services.collection.dropped_issue import discover_issues
from backend.app.services.settings import collection_payload, get_effective_settings

logger = logging.getLogger("kesco.collections")

router = APIRouter()
_collection_lock = asyncio.Lock()


class CollectionRequest(BaseModel):
    # 구버전 화면이 보내던 검색식·키워드 필드는 호환상 무시한다. 수집 설정은
    # config 기본값과 settings 테이블 override만 사용한다.
    model_config = ConfigDict(extra="ignore")

    report_date: str | None = Field(
        default=None, validation_alias=AliasChoices("report_date", "reportDate")
    )
    lookback_hours: int = Field(
        default=24,
        ge=1,
        validation_alias=AliasChoices("lookback_hours", "lookbackHours"),
    )


def _serialize_run(row) -> dict[str, Any]:
    source_filter_stats = (
        json.loads(row["source_filter_stats_json"])
        if row["source_filter_stats_json"]
        else {}
    )
    return {
        "id": row["id"],
        "reportDate": row["report_date"],
        "startedAt": row["started_at"],
        "finishedAt": row["finished_at"],
        "status": row["status"],
        "lookbackHours": row["lookback_hours"],
        "rawCount": row["raw_count"],
        "acceptedCount": row["accepted_count"],
        "uniqueCount": row["unique_count"],
        "staleReusedCount": row["stale_reused_count"],
        "warningCount": row["warning_count"],
        "errorCount": row["error_count"],
        "source_filter_stats": source_filter_stats,
    }


def _serialize_provider(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "provider": row["provider"],
        "queryGroupId": row["query_group_id"],
        "status": row["status"],
        "startedAt": row["started_at"],
        "finishedAt": row["finished_at"],
        "rawCount": row["raw_count"],
        "acceptedCount": row["accepted_count"],
        "duplicateCount": row["duplicate_count"],
        "staleReusedCount": row["stale_reused_count"],
        "warningMessage": row["warning_message"],
        "errorCode": row["error_code"],
        "errorMessage": row["error_message"],
    }


@router.post("/api/collections")
async def create_collection(request: CollectionRequest) -> dict[str, Any]:
    settings, _ = get_effective_settings()
    enabled_queries = [query for query in settings.queries if query.enabled and query.query.strip()]
    if not enabled_queries and not (
        settings.enableYonhap or settings.enableOpmPress or settings.enableMePress
    ):
        return error_response(
            "COLLECTION_NO_SOURCE", "활성화된 검색식이나 언론기사 수집원이 없습니다. 설정을 확인해 주세요."
        )
    payload = collection_payload(
        settings, request.report_date, request.lookback_hours, scope="article"
    )
    return await _execute_collection(payload)


@router.post("/api/government-press-releases/collections")
async def create_government_press_release_collection(
    request: CollectionRequest,
) -> dict[str, Any]:
    settings, _ = get_effective_settings()
    policy_configured = bool(os.environ.get("POLICY_BRIEFING_SERVICE_KEY", "").strip())
    if not policy_configured:
        return error_response(
            "COLLECTION_NO_SOURCE",
            "공공데이터포털 정책브리핑 API 서비스키가 설정되지 않았습니다.",
        )
    payload = collection_payload(
        settings, request.report_date, request.lookback_hours, scope="government"
    )
    return await _execute_collection(payload)


async def _execute_collection(payload: dict[str, Any]) -> dict[str, Any]:

    if _collection_lock.locked():
        return error_response(
            "COLLECTION_ALREADY_RUNNING", "다른 기사 수집이 실행 중입니다. 완료 후 다시 시도해 주세요."
        )
    try:
        async with _collection_lock:
            data = await run_collection(payload)
    except Exception:
        logger.exception("수집 실행 중 처리되지 않은 오류")
        return error_response("COLLECTION_INTERNAL_ERROR", "수집 처리 중 서버 오류가 발생했습니다.")

    return ok_envelope(data)


@router.get("/api/collections/latest")
async def get_latest_collection(report_date: str = Query(...)) -> Any:
    connection = get_connection()
    try:
        row = run_repo.get_latest_run(connection, report_date)
        if row is None:
            return error_response("COLLECTION_FAILED", f"{report_date}에 수집 이력이 없습니다.")
        providers = run_repo.list_providers(connection, row["id"])
    finally:
        connection.close()
    data = _serialize_run(row)
    data["providers"] = [_serialize_provider(p) for p in providers]
    return ok_envelope(data)


@router.get("/api/collections/discovered-issues")
async def get_discovered_issues(report_date: str = Query(...)) -> Any:
    """관련도 미달로 제외됐던 기사에서 '많이 다뤄진 사건'을 묶어 돌려준다."""
    connection = get_connection()
    try:
        rows = dropped_repo.list_for_report_date(connection, report_date)
    finally:
        connection.close()
    issues = discover_issues(rows)
    return ok_envelope(
        {
            "reportDate": report_date,
            "pooledCount": len(rows),
            "issues": issues,
        }
    )


@router.get("/api/collections/{collection_run_id}")
async def get_collection(collection_run_id: str) -> Any:
    connection = get_connection()
    try:
        row = run_repo.get_run(connection, collection_run_id)
        if row is None:
            return error_response("COLLECTION_FAILED", "수집 실행 이력을 찾을 수 없습니다.")
        providers = run_repo.list_providers(connection, row["id"])
    finally:
        connection.close()
    data = _serialize_run(row)
    data["providers"] = [_serialize_provider(p) for p in providers]
    return ok_envelope(data)
