from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from backend.app.api.envelope import error_response, ok_envelope
from backend.app.core.clock import now_iso
from backend.app.repositories import ai_run_repository as ai_runs_repo
from backend.app.repositories import article_repository as articles_repo
from backend.app.repositories import briefing_repository as briefings_repo
from backend.app.repositories import issue_repository as issues_repo
from backend.app.repositories.database import get_connection
from backend.app.services.ai.analyzer import (
    AnalysisError,
    analyze,
    build_evidence_input,
    format_analysis,
    input_signature,
)
from backend.app.services.ai.ollama_client import OllamaError, default_client
from backend.app.services.ai.prompt_builder import PROMPT_VERSION

router = APIRouter()


class AnalyzeRequest(BaseModel):
    expectedRevision: int
    model: str


def _issue_map(connection, report_date: str) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for issue in issues_repo.list_for_report_date(connection, report_date):
        for article_id in issue.get("articleIds") or []:
            result.setdefault(article_id, []).append(issue["id"])
    return result


def _inputs(connection, report_date: str) -> tuple[list[dict[str, Any]], dict[str, str]]:
    articles = articles_repo.list_candidates(connection, report_date, include_dismissed=False)
    return build_evidence_input(articles, _issue_map(connection, report_date))


def ai_state(connection, briefing, desired_model: str | None = None) -> dict[str, Any]:
    latest = ai_runs_repo.latest(connection, briefing["id"])
    success = ai_runs_repo.latest_success(connection, briefing["id"])
    serialized_success = None
    if success is not None:
        evidence_input, _ = _inputs(connection, briefing["report_date"])
        model = desired_model or success["model"]
        stale = input_signature(model, evidence_input) != success["input_signature"]
        serialized_success = ai_runs_repo.serialize(success, stale=stale)
    return {
        "lastSuccessfulRun": serialized_success,
        "latestRun": ai_runs_repo.serialize(latest),
        "currentError": latest["error_message"] if latest is not None and latest["status"] == "failed" else None,
    }


def _error_with_preserved_result(code: str, message: str, briefing_id: str, run_id: str):
    connection = get_connection()
    try:
        briefing = briefings_repo.get_by_id(connection, briefing_id)
        details = ai_state(connection, briefing) if briefing is not None else {}
        details["runId"] = run_id
    finally:
        connection.close()
    return error_response(code, message, details)


@router.post("/api/briefings/{report_date}/analyze")
async def analyze_briefing(report_date: str, body: AnalyzeRequest, request: Request) -> Any:
    connection = get_connection()
    try:
        briefing = briefings_repo.get_by_date(connection, report_date)
        if briefing is None:
            return error_response("BRIEFING_NOT_FOUND", f"{report_date} 작업본이 없습니다.")
        if briefing["status"] == "final":
            return error_response("BRIEFING_FINALIZED", "최종 확정된 작업본은 분석할 수 없습니다.")
        if briefing["revision"] != body.expectedRevision:
            return error_response("BRIEFING_REVISION_CONFLICT", "다른 화면에서 브리핑이 변경됐습니다.")
        evidence_input, evidence = _inputs(connection, report_date)
        if not evidence:
            return error_response("AI_SCHEMA_INVALID", "분석할 선정 기사가 없습니다.")
        signature = input_signature(body.model, evidence_input)
        request_snapshot = {
            "reportDate": report_date,
            "preparedBy": briefing["prepared_by"] or "",
            "articles": evidence_input,
            "attemptLimit": 2,
        }
        with connection:
            run = ai_runs_repo.create(
                connection,
                briefing_id=briefing["id"],
                model=body.model,
                prompt_version=PROMPT_VERSION,
                input_signature=signature,
                request=request_snapshot,
                evidence=evidence,
            )
        run_id = run["id"]
        briefing_id = briefing["id"]
        prepared_by = briefing["prepared_by"] or ""
    finally:
        connection.close()

    client = getattr(request.app.state, "ollama_client", default_client)
    try:
        output = await asyncio.to_thread(
            analyze,
            client,
            model=body.model,
            report_date=report_date,
            prepared_by=prepared_by,
            evidence_input=evidence_input,
            evidence=evidence,
        )
    except AnalysisError as exc:
        connection = get_connection()
        try:
            with connection:
                ai_runs_repo.finish_failed(
                    connection,
                    run_id,
                    f"{exc.code}: {exc}",
                    {"raw": exc.raw_response, "attempts": exc.attempts},
                )
        finally:
            connection.close()
        return _error_with_preserved_result(exc.code, str(exc), briefing_id, run_id)
    except (OllamaError, OSError, TimeoutError) as exc:
        connection = get_connection()
        try:
            with connection:
                ai_runs_repo.finish_failed(connection, run_id, f"AI_UNAVAILABLE: {exc}")
        finally:
            connection.close()
        return _error_with_preserved_result(
            "AI_UNAVAILABLE", "Ollama에 연결할 수 없습니다.", briefing_id, run_id
        )

    connection = get_connection()
    try:
        current = briefings_repo.get_by_date(connection, report_date)
        current_input, _ = _inputs(connection, report_date)
        if (
            current is None
            or current["revision"] != body.expectedRevision
            or input_signature(body.model, current_input) != signature
        ):
            with connection:
                ai_runs_repo.finish_failed(
                    connection, run_id, "AI_INPUT_STALE: 분석 중 선정 기사나 메모가 변경됐습니다."
                )
            return _error_with_preserved_result(
                "AI_INPUT_STALE",
                "분석 중 선정 기사나 메모가 변경되어 결과를 적용하지 않았습니다.",
                briefing_id,
                run_id,
            )

        preserve_edited = current["summary_mode"] == "ai-edited"
        patch = {
            "aiModel": body.model,
            "aiPromptVersion": PROMPT_VERSION,
            "aiGeneratedAt": now_iso(),
            "aiInputSignature": signature,
        }
        if not preserve_edited:
            patch.update(
                {"situationSummary": format_analysis(output.result), "summaryMode": "ai"}
            )
        with connection:
            ai_runs_repo.finish_success(
                connection,
                run_id,
                {"analysis": output.result, "attempts": output.attempts},
            )
            updated = briefings_repo.create_or_update(
                connection, report_date, body.expectedRevision, patch
            )
        state = ai_state(connection, updated, body.model)
    except (briefings_repo.RevisionConflict, briefings_repo.BriefingFinalized):
        with connection:
            ai_runs_repo.finish_failed(
                connection, run_id, "AI_INPUT_STALE: 분석 결과 적용 직전에 작업본이 변경됐습니다."
            )
        return _error_with_preserved_result(
            "AI_INPUT_STALE", "분석 결과 적용 직전에 작업본이 변경됐습니다.", briefing_id, run_id
        )
    finally:
        connection.close()

    return ok_envelope(
        {
            "run": state["lastSuccessfulRun"],
            "briefingRevision": updated["revision"],
            "situationSummary": updated["situation_summary"],
            "summaryMode": updated["summary_mode"],
            "appliedToSummary": not preserve_edited,
        },
        meta={"revision": updated["revision"]},
    )
