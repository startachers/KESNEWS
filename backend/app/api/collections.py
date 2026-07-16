from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from backend.app.api.envelope import error_response, ok_envelope
from backend.app.repositories import run_repository as run_repo
from backend.app.repositories.database import get_connection
from backend.app.services.collection.collector import run_collection

logger = logging.getLogger("kesco.collections")

router = APIRouter()
_collection_lock = asyncio.Lock()


class CollectionQuery(BaseModel):
    id: str = "direct"
    label: str = ""
    query: str = ""


class CollectionRequest(BaseModel):
    reportDate: str | None = None
    lookbackHours: int = 48
    maxRecordsPerQuery: int = 50
    collectionLimit: int = 400
    enableYonhap: bool = True
    queries: list[CollectionQuery] = Field(default_factory=list)
    coreKeywords: list[str] = Field(default_factory=list)
    riskKeywords: list[str] = Field(default_factory=list)
    positiveKeywords: list[str] = Field(default_factory=list)
    excludeKeywords: list[str] = Field(default_factory=list)
    endpoint: str = ""


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
    enabled_queries = [q for q in request.queries if q.query.strip()]
    if not enabled_queries and not request.enableYonhap:
        return error_response(
            "COLLECTION_NO_SOURCE", "활성화된 검색식이나 뉴스 수집원이 없습니다. 설정을 확인해 주세요."
        )

    payload = {
        "reportDate": request.reportDate,
        "lookbackHours": request.lookbackHours,
        "maxRecordsPerQuery": request.maxRecordsPerQuery,
        "collectionLimit": request.collectionLimit,
        "enableYonhap": request.enableYonhap,
        "queries": [q.model_dump() for q in enabled_queries],
        "coreKeywords": request.coreKeywords,
        "riskKeywords": request.riskKeywords,
        "positiveKeywords": request.positiveKeywords,
        "excludeKeywords": request.excludeKeywords,
        "endpoint": request.endpoint,
    }

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
