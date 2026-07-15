from __future__ import annotations

import sqlite3
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.app.api.envelope import error_response, ok_envelope
from backend.app.api.analysis import ai_state
from backend.app.repositories import briefing_repository as repo
from backend.app.repositories import issue_repository as issues_repo
from backend.app.repositories.database import get_connection

router = APIRouter()


class BriefingPatch(BaseModel):
    preparedBy: str | None = None
    situationSummary: str | None = None
    actionNote: str | None = None
    summaryMode: str | None = None
    status: Literal["draft", "reviewed"] | None = None
    aiModel: str | None = None
    aiPromptVersion: str | None = None
    aiGeneratedAt: str | None = None
    aiInputSignature: str | None = None


class BriefingPutRequest(BaseModel):
    expectedRevision: int
    patch: BriefingPatch = Field(default_factory=BriefingPatch)


class ArticleStatePatchRequest(BaseModel):
    expectedRevision: int
    selected: bool | None = None
    starred: bool | None = None
    note: str | None = None
    dismissed: bool | None = None
    sortOrder: int | None = None


class ArticleOrderRequest(BaseModel):
    expectedRevision: int
    articleIds: list[str] = Field(default_factory=list)


class IssueStatePatchRequest(BaseModel):
    expectedRevision: int
    selected: bool | None = None
    starred: bool | None = None
    note: str | None = None
    sortOrder: int | None = None


def _serialize(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "reportDate": row["report_date"],
        "preparedBy": row["prepared_by"],
        "status": row["status"],
        "situationSummary": row["situation_summary"],
        "actionNote": row["action_note"],
        "summaryMode": row["summary_mode"],
        "aiModel": row["ai_model"],
        "aiPromptVersion": row["ai_prompt_version"],
        "aiGeneratedAt": row["ai_generated_at"],
        "aiInputSignature": row["ai_input_signature"],
        "revision": row["revision"],
        "latestFinalVersion": row["latest_final_version"],
        "finalizedAt": row["finalized_at"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


@router.get("/api/briefings/{report_date}")
async def get_briefing(report_date: str) -> Any:
    connection = get_connection()
    try:
        row = repo.get_by_date(connection, report_date)
        state = ai_state(connection, row) if row is not None else None
    finally:
        connection.close()
    if row is None:
        return error_response("BRIEFING_NOT_FOUND", f"{report_date} 작업본이 없습니다.")
    data = _serialize(row)
    data["aiState"] = state
    return ok_envelope(data, meta={"revision": row["revision"]})


@router.put("/api/briefings/{report_date}")
async def put_briefing(report_date: str, request: BriefingPutRequest) -> Any:
    connection = get_connection()
    try:
        with connection:
            row = repo.create_or_update(
                connection,
                report_date,
                request.expectedRevision,
                request.patch.model_dump(exclude_none=True),
            )
    except repo.RevisionConflict:
        return error_response(
            "BRIEFING_REVISION_CONFLICT", "다른 화면에서 브리핑이 변경됐습니다."
        )
    except repo.BriefingFinalized:
        return error_response("BRIEFING_FINALIZED", "최종 확정된 작업본은 수정할 수 없습니다.")
    finally:
        connection.close()
    return ok_envelope(_serialize(row), meta={"revision": row["revision"]})


@router.patch("/api/briefings/{report_date}/articles/{article_id}")
async def patch_briefing_article(
    report_date: str, article_id: str, request: ArticleStatePatchRequest
) -> Any:
    fields = request.model_dump(exclude={"expectedRevision"}, exclude_none=True)
    connection = get_connection()
    try:
        with connection:
            row = repo.patch_article_state(
                connection, report_date, article_id, request.expectedRevision, fields
            )
    except repo.BriefingNotFound:
        return error_response("BRIEFING_NOT_FOUND", f"{report_date} 작업본이 없습니다.")
    except repo.BriefingFinalized:
        return error_response("BRIEFING_FINALIZED", "최종 확정된 작업본은 수정할 수 없습니다.")
    except repo.RevisionConflict:
        return error_response(
            "BRIEFING_REVISION_CONFLICT", "다른 화면에서 브리핑이 변경됐습니다."
        )
    finally:
        connection.close()
    return ok_envelope(_serialize(row), meta={"revision": row["revision"]})


@router.put("/api/briefings/{report_date}/article-order")
async def put_article_order(report_date: str, request: ArticleOrderRequest) -> Any:
    connection = get_connection()
    try:
        with connection:
            row = repo.reorder_articles(
                connection, report_date, request.expectedRevision, request.articleIds
            )
    except repo.BriefingNotFound:
        return error_response("BRIEFING_NOT_FOUND", f"{report_date} 작업본이 없습니다.")
    except repo.BriefingFinalized:
        return error_response("BRIEFING_FINALIZED", "최종 확정된 작업본은 수정할 수 없습니다.")
    except repo.RevisionConflict:
        return error_response(
            "BRIEFING_REVISION_CONFLICT", "다른 화면에서 브리핑이 변경됐습니다."
        )
    finally:
        connection.close()
    return ok_envelope(_serialize(row), meta={"revision": row["revision"]})


@router.patch("/api/briefings/{report_date}/issues/{issue_id}")
async def patch_briefing_issue(
    report_date: str, issue_id: str, request: IssueStatePatchRequest
) -> Any:
    fields = request.model_dump(exclude={"expectedRevision"}, exclude_none=True)
    connection = get_connection()
    try:
        if issues_repo.get(connection, issue_id) is None:
            return error_response("ISSUE_NOT_FOUND", "이슈를 찾을 수 없습니다.")
        with connection:
            row = repo.patch_issue_state(
                connection, report_date, issue_id, request.expectedRevision, fields
            )
    except repo.BriefingNotFound:
        return error_response("BRIEFING_NOT_FOUND", f"{report_date} 작업본이 없습니다.")
    except repo.BriefingFinalized:
        return error_response("BRIEFING_FINALIZED", "최종 확정된 작업본은 수정할 수 없습니다.")
    except repo.RevisionConflict:
        return error_response(
            "BRIEFING_REVISION_CONFLICT", "다른 화면에서 브리핑이 변경됐습니다."
        )
    finally:
        connection.close()
    return ok_envelope(_serialize(row), meta={"revision": row["revision"]})
