from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.app.services.collection.collector import run_collection

logger = logging.getLogger("kesco.collections")

router = APIRouter()


class CollectionQuery(BaseModel):
    id: str = "direct"
    label: str = ""
    query: str = ""


class CollectionRequest(BaseModel):
    reportDate: str | None = None
    lookbackHours: int = 48
    maxRecordsPerQuery: int = 50
    collectionLimit: int = 200
    enableYonhap: bool = True
    queries: list[CollectionQuery] = Field(default_factory=list)
    coreKeywords: list[str] = Field(default_factory=list)
    riskKeywords: list[str] = Field(default_factory=list)
    positiveKeywords: list[str] = Field(default_factory=list)
    excludeKeywords: list[str] = Field(default_factory=list)
    endpoint: str = ""
    existingArticles: list[dict[str, Any]] = Field(default_factory=list)


def _error_envelope(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "data": None, "error": {"code": code, "message": message, "details": {}}, "meta": {}}


@router.post("/api/collections")
async def create_collection(request: CollectionRequest) -> dict[str, Any]:
    enabled_queries = [q for q in request.queries if q.query.strip()]
    if not enabled_queries and not request.enableYonhap:
        return _error_envelope(
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
        "existingArticles": request.existingArticles,
    }

    try:
        data = await run_collection(payload)
    except Exception:
        logger.exception("수집 실행 중 처리되지 않은 오류")
        return _error_envelope("COLLECTION_INTERNAL_ERROR", "수집 처리 중 서버 오류가 발생했습니다.")

    return {"ok": True, "data": data, "error": None, "meta": {}}
