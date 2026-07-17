from __future__ import annotations

import sqlite3
from typing import Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from backend.app.api.envelope import error_response, ok_envelope
from backend.app.api.analysis import ai_state
from backend.app.core.clock import today_seoul
from backend.app.repositories import briefing_repository as repo
from backend.app.repositories import issue_repository as issues_repo
from backend.app.repositories.database import backup_database, get_connection

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
    topIssue: bool | None = None
    note: str | None = None
    dismissed: bool | None = None
    sortOrder: int | None = None
    directCoverage: bool | None = None


class ArticleOrderRequest(BaseModel):
    expectedRevision: int
    articleIds: list[str] = Field(default_factory=list)


class IssueStatePatchRequest(BaseModel):
    expectedRevision: int
    selected: bool | None = None
    starred: bool | None = None
    note: str | None = None
    sortOrder: int | None = None
    editorReviewStars: int | None = Field(default=None, ge=1, le=5)
    editorReviewReason: str | None = Field(default=None, max_length=500)
    directCoverage: bool | None = None
    articleId: str | None = None


class DailyWorkResetRequest(BaseModel):
    expectedRevision: int
    confirmation: Literal["RESET_TODAY"]


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


@router.get("/api/briefings")
async def list_briefings(limit: int = Query(default=100, ge=1, le=365)) -> Any:
    connection = get_connection()
    try:
        rows = repo.list_recent(connection, limit)
    finally:
        connection.close()
    return ok_envelope({"briefings": [_serialize(row) for row in rows]})


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


@router.post("/api/briefings/{report_date}/reset")
async def reset_daily_work(report_date: str, request: DailyWorkResetRequest) -> Any:
    if report_date != today_seoul():
        return error_response(
            "DAILY_RESET_TODAY_ONLY", "오늘 날짜의 작업만 초기화할 수 있습니다."
        )
    connection = get_connection()
    try:
        briefing = repo.get_by_date(connection, report_date)
        if briefing is None:
            return error_response("BRIEFING_NOT_FOUND", f"{report_date} 작업본이 없습니다.")
        if briefing["status"] == "final":
            return error_response(
                "BRIEFING_FINALIZED", "최종 확정된 작업본은 초기화할 수 없습니다."
            )
        if briefing["revision"] != request.expectedRevision:
            return error_response(
                "BRIEFING_REVISION_CONFLICT",
                "다른 화면에서 브리핑이 변경됐습니다.",
            )
    finally:
        connection.close()

    try:
        backup_path = backup_database()
    except sqlite3.DatabaseError as exc:
        return error_response("DAILY_RESET_BACKUP_FAILED", f"초기화 전 백업에 실패했습니다: {exc}")

    connection = get_connection()
    try:
        with connection:
            row, deleted = repo.reset_daily_work(
                connection, report_date, request.expectedRevision
            )
    except repo.BriefingNotFound:
        return error_response("BRIEFING_NOT_FOUND", f"{report_date} 작업본이 없습니다.")
    except repo.BriefingFinalized:
        return error_response(
            "BRIEFING_FINALIZED", "최종 확정된 작업본은 초기화할 수 없습니다."
        )
    except repo.RevisionConflict:
        return error_response(
            "BRIEFING_REVISION_CONFLICT", "다른 화면에서 브리핑이 변경됐습니다."
        )
    except repo.DailyWorkResetBlocked:
        return error_response(
            "DAILY_RESET_ACTIVE_RUN",
            "기사 수집이나 AI 분석이 실행 중입니다. 완료 또는 취소 후 초기화해 주세요.",
        )
    except sqlite3.IntegrityError:
        return error_response(
            "DAILY_RESET_CONSTRAINT_FAILED",
            "다른 날짜와 공유된 기록을 안전하게 분리하지 못해 초기화를 중단했습니다.",
        )
    finally:
        connection.close()
    data = _serialize(row)
    data.update(
        {
            "deleted": deleted,
            "backupFile": backup_path.name if backup_path is not None else None,
        }
    )
    return ok_envelope(data, meta={"revision": row["revision"]})


@router.patch("/api/briefings/{report_date}/articles/{article_id}")
async def patch_briefing_article(
    report_date: str, article_id: str, request: ArticleStatePatchRequest
) -> Any:
    fields = request.model_dump(exclude={"expectedRevision"})
    fields = {key: value for key, value in fields.items() if key in request.model_fields_set}
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
    except repo.TopIssueLimitExceeded:
        return error_response(
            "TOP_ISSUE_LIMIT_EXCEEDED", "Top Issues는 최대 6개까지 선정할 수 있습니다."
        )
    except repo.DirectCoverageNotSelectable:
        return error_response(
            "DIRECT_COVERAGE_NOT_SELECTABLE",
            "공사 직접 보도는 CEO 일반 브리핑에 선정할 수 없습니다.",
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
    fields = request.model_dump(exclude={"expectedRevision"})
    fields = {key: value for key, value in fields.items() if key in request.model_fields_set}
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
    except repo.TopIssueLimitExceeded:
        return error_response(
            "TOP_ISSUE_LIMIT_EXCEEDED", "Top Issues는 최대 6개까지 선정할 수 있습니다."
        )
    except repo.DirectCoverageNotSelectable:
        return error_response(
            "DIRECT_COVERAGE_NOT_SELECTABLE",
            "공사 직접 보도는 CEO 일반 브리핑이나 Top Issues에 선정할 수 없습니다.",
        )
    finally:
        connection.close()
    return ok_envelope(_serialize(row), meta={"revision": row["revision"]})
