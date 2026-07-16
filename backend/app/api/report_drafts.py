from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from backend.app.api.envelope import error_response, ok_envelope
from backend.app.repositories import briefing_repository as briefing_repo
from backend.app.repositories import report_draft_repository as draft_repo
from backend.app.repositories.database import get_connection
from backend.app.services.reports.report_draft import (
    ReportDraftInvalid,
    build_exchange_context,
    content_from_plain_text,
    normalize_external_payload,
    validate_content,
)

router = APIRouter()


class ReportDraftPutRequest(BaseModel):
    expectedRevision: int
    sourceType: Literal["gemma", "external", "manual"] = "external"
    sourceLabel: str = Field(default="", max_length=100)
    inputSignature: str
    content: dict[str, Any]
    basedOnAiRunId: str | None = None


def _briefing_or_error(connection, report_date: str):
    briefing = briefing_repo.get_by_date(connection, report_date)
    if briefing is None:
        return None, error_response("BRIEFING_NOT_FOUND", f"{report_date} 작업본이 없습니다.")
    return briefing, None


@router.get("/api/briefings/{report_date}/report-draft")
async def get_report_draft(report_date: str) -> Any:
    connection = get_connection()
    try:
        briefing, error = _briefing_or_error(connection, report_date)
        if error:
            return error
        context = build_exchange_context(connection, report_date)
        row = draft_repo.get(connection, briefing["id"])
        data = draft_repo.serialize(
            row, stale=bool(row is not None and row["input_signature"] != context.signature)
        )
    finally:
        connection.close()
    return ok_envelope(
        {
            "draft": data,
            "inputSignature": context.signature,
            "evidence": context.evidence,
            "selectedCount": len(context.articles),
        }
    )


@router.post("/api/briefings/{report_date}/report-draft/validate")
async def validate_report_draft(report_date: str, request: Request) -> Any:
    payload = await request.json()
    connection = get_connection()
    try:
        briefing, error = _briefing_or_error(connection, report_date)
        if error:
            return error
        if briefing["status"] == "final":
            return error_response("BRIEFING_FINALIZED", "최종 확정된 작업본은 수정할 수 없습니다.")
        context = build_exchange_context(connection, report_date)
        supplied_signature = str(payload.get("inputSignature") or "") or None
        if isinstance(payload.get("text"), str):
            content = content_from_plain_text(payload["text"], list(context.evidence))
        else:
            supplied_signature, content = normalize_external_payload(payload)
        if payload.get("reportDate") and str(payload["reportDate"]) != report_date:
            return error_response("REPORT_DRAFT_INVALID", "외부 AI 결과의 보고일이 현재 브리핑과 다릅니다.")
        if not supplied_signature:
            return error_response("REPORT_DRAFT_INVALID", "외부 AI 결과에 inputSignature가 없습니다.")
        if supplied_signature != context.signature:
            return error_response(
                "REPORT_DRAFT_STALE",
                "Markdown 내보내기 이후 선정 기사·전문·태그가 변경됐습니다. 다시 내려받아 분석해 주세요.",
                {"currentInputSignature": context.signature},
            )
        normalized = validate_content(content, context.evidence)
    except ReportDraftInvalid as exc:
        return error_response(
            "REPORT_DRAFT_INVALID",
            "외부 AI 결과 형식이나 근거가 올바르지 않습니다.",
            {"reason": str(exc)},
        )
    finally:
        connection.close()
    return ok_envelope(
        {
            "content": normalized,
            "inputSignature": context.signature,
            "evidence": context.evidence,
            "sourceLabel": str(payload.get("sourceLabel") or ""),
        }
    )


@router.put("/api/briefings/{report_date}/report-draft")
async def put_report_draft(report_date: str, request: ReportDraftPutRequest) -> Any:
    connection = get_connection()
    try:
        briefing, error = _briefing_or_error(connection, report_date)
        if error:
            return error
        if briefing["status"] == "final":
            return error_response("BRIEFING_FINALIZED", "최종 확정된 작업본은 수정할 수 없습니다.")
        if briefing["revision"] != request.expectedRevision:
            return error_response("BRIEFING_REVISION_CONFLICT", "다른 화면에서 브리핑이 변경됐습니다.")
        context = build_exchange_context(connection, report_date)
        if request.inputSignature != context.signature:
            return error_response(
                "REPORT_DRAFT_STALE",
                "CEO 보고 편집 중 선정 기사·전문·태그가 변경됐습니다.",
                {"currentInputSignature": context.signature},
            )
        try:
            content = validate_content(request.content, context.evidence)
        except ReportDraftInvalid as exc:
            return error_response(
                "REPORT_DRAFT_INVALID",
                "CEO 보고 편집본의 형식이나 근거가 올바르지 않습니다.",
                {"reason": str(exc)},
            )
        with connection:
            row = draft_repo.upsert(
                connection,
                briefing_id=briefing["id"],
                source_type=request.sourceType,
                source_label=request.sourceLabel,
                content=content,
                evidence=context.evidence,
                input_signature=context.signature,
                based_on_ai_run_id=request.basedOnAiRunId,
            )
            updated = briefing_repo.bump_revision(
                connection, briefing["id"], request.expectedRevision
            )
    except briefing_repo.RevisionConflict:
        return error_response("BRIEFING_REVISION_CONFLICT", "다른 화면에서 브리핑이 변경됐습니다.")
    finally:
        connection.close()
    return ok_envelope(
        {"draft": draft_repo.serialize(row), "revision": updated["revision"]},
        meta={"revision": updated["revision"]},
    )
