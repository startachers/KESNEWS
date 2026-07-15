from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse

_ERROR_STATUS = {
    "BRIEFING_NOT_FOUND": 404,
    "BRIEFING_REVISION_CONFLICT": 409,
    "BRIEFING_FINALIZED": 409,
    "ARTICLE_NOT_FOUND": 404,
    "ARTICLE_IN_USE": 409,
    "ISSUE_NOT_FOUND": 404,
    "CLUSTER_RUN_NOT_FOUND": 404,
    "CLUSTER_RUN_STALE": 409,
    "AI_INPUT_STALE": 409,
    "AI_SCHEMA_INVALID": 422,
    "AI_EVIDENCE_INVALID": 422,
    "AI_UNAVAILABLE": 503,
    "IMPORT_SCHEMA_UNSUPPORTED": 400,
    "IMPORT_CONFLICT": 409,
    "COLLECTION_NO_SOURCE": 400,
    "COLLECTION_INTERNAL_ERROR": 500,
}


def ok_envelope(data: Any = None, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"ok": True, "data": data, "error": None, "meta": meta or {}}


def error_response(code: str, message: str, details: dict[str, Any] | None = None) -> JSONResponse:
    status_code = _ERROR_STATUS.get(code, 400)
    body = {
        "ok": False,
        "data": None,
        "error": {"code": code, "message": message, "details": details or {}},
        "meta": {},
    }
    return JSONResponse(status_code=status_code, content=body)
