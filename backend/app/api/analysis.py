from __future__ import annotations

import asyncio
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    select_articles,
)
from backend.app.services.ai.ollama_client import (
    DEFAULT_CONTEXT_LENGTH,
    OllamaError,
    default_client,
)
from backend.app.services.ai.runtime import (
    AnalysisCancelled,
    CancellationToken,
    analysis_registry,
)
from backend.app.services.ai.prompt_builder import PROMPT_VERSION
from backend.app.services.extraction import article_body

router = APIRouter()
ANALYSIS_TIMEOUT_SECONDS = max(30, int(os.environ.get("KESCO_AI_TIMEOUT_SECONDS", "300")))


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


def _refresh_selected_bodies(report_date: str) -> None:
    connection = get_connection()
    try:
        selected = select_articles(
            articles_repo.list_candidates(connection, report_date, include_dismissed=False)
        )
        pending = [item for item in selected if not item.get("bodyText")]
        if not pending:
            return

        results: dict[str, article_body.BodyFetchResult] = {}
        with ThreadPoolExecutor(max_workers=min(8, len(pending))) as executor:
            futures = {
                executor.submit(article_body.fetch_article_body, item.get("url") or ""): item
                for item in pending
            }
            for future in as_completed(futures):
                item = futures[future]
                try:
                    results[item["id"]] = future.result()
                except Exception as exc:  # 개별 언론사 파서 실패가 전체 분석을 막지 않는다.
                    results[item["id"]] = article_body.BodyFetchResult(
                        "", "missing", f"기사 전문 수집 실패: {exc}"
                    )

        with connection:
            for item in pending:
                result = results[item["id"]]
                status = result.status
                if not result.body_text and item.get("description"):
                    status = "summary_only"
                articles_repo.update_article_body(
                    connection,
                    item["id"],
                    body_text=result.body_text,
                    body_status=status,
                    body_error=result.error,
                )
    finally:
        connection.close()


def ai_state(
    connection,
    briefing,
    desired_model: str | None = None,
    desired_context_length: int | None = None,
) -> dict[str, Any]:
    latest = ai_runs_repo.latest(connection, briefing["id"])
    success = ai_runs_repo.latest_success(connection, briefing["id"])
    serialized_success = None
    if success is not None:
        evidence_input, _ = _inputs(connection, briefing["report_date"])
        model = desired_model or success["model"]
        context_length = desired_context_length or default_client.context_length
        stale = (
            input_signature(model, evidence_input, context_length) != success["input_signature"]
        )
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


def _context_length(client: Any, model: str) -> int:
    resolver = getattr(client, "context_length_for", None)
    if callable(resolver):
        return int(resolver(model))
    return int(getattr(client, "context_length", DEFAULT_CONTEXT_LENGTH))


@router.post("/api/briefings/{report_date}/analysis/cancel")
async def cancel_analysis(report_date: str) -> Any:
    connection = get_connection()
    try:
        briefing = briefings_repo.get_by_date(connection, report_date)
        if briefing is None:
            return error_response("BRIEFING_NOT_FOUND", f"{report_date} 작업본이 없습니다.")
        run_id = analysis_registry.cancel_for_briefing(briefing["id"], "user")
        if run_id is None:
            running = ai_runs_repo.latest_running(connection)
            if running is not None and running["briefing_id"] == briefing["id"]:
                with connection:
                    ai_runs_repo.finish_failed(
                        connection,
                        running["id"],
                        "AI_INTERRUPTED: 실행 프로세스가 없어 중단 처리했습니다.",
                    )
                run_id = running["id"]
            else:
                return error_response("AI_CANCELLED", "현재 취소할 AI 분석이 없습니다.")
    finally:
        connection.close()
    return ok_envelope({"runId": run_id, "cancelRequested": True})


@router.post("/api/briefings/{report_date}/analyze")
async def analyze_briefing(report_date: str, body: AnalyzeRequest, request: Request) -> Any:
    client = getattr(request.app.state, "ollama_client", default_client)
    context_length = _context_length(client, body.model)
    active_run_id = analysis_registry.active_run_id()
    if active_run_id is not None:
        return error_response(
            "AI_ALREADY_RUNNING",
            "다른 AI 분석이 이미 실행 중입니다. 완료하거나 취소한 뒤 다시 시도해 주세요.",
            {"runId": active_run_id},
        )
    connection = get_connection()
    registered = False
    try:
        briefing = briefings_repo.get_by_date(connection, report_date)
        if briefing is None:
            return error_response("BRIEFING_NOT_FOUND", f"{report_date} 작업본이 없습니다.")
        if briefing["status"] == "final":
            return error_response("BRIEFING_FINALIZED", "최종 확정된 작업본은 분석할 수 없습니다.")
        if briefing["revision"] != body.expectedRevision:
            return error_response("BRIEFING_REVISION_CONFLICT", "다른 화면에서 브리핑이 변경됐습니다.")
        await asyncio.to_thread(_refresh_selected_bodies, report_date)
        connection.execute("BEGIN IMMEDIATE")
        orphan = ai_runs_repo.latest_running(connection)
        if orphan is not None:
            ai_runs_repo.finish_failed(
                connection,
                orphan["id"],
                "AI_INTERRUPTED: 앱 재시작 전에 끝나지 않은 실행을 정리했습니다.",
            )
        briefing = briefings_repo.get_by_date(connection, report_date)
        if briefing is None:
            connection.rollback()
            return error_response("BRIEFING_NOT_FOUND", f"{report_date} 작업본이 없습니다.")
        if briefing["status"] == "final":
            connection.rollback()
            return error_response("BRIEFING_FINALIZED", "최종 확정된 작업본은 분석할 수 없습니다.")
        if briefing["revision"] != body.expectedRevision:
            connection.rollback()
            return error_response("BRIEFING_REVISION_CONFLICT", "다른 화면에서 브리핑이 변경됐습니다.")
        evidence_input, evidence = _inputs(connection, report_date)
        if not evidence:
            connection.rollback()
            return error_response("AI_SCHEMA_INVALID", "분석할 선정 기사가 없습니다.")
        signature = input_signature(body.model, evidence_input, context_length)
        request_snapshot = {
            "reportDate": report_date,
            "preparedBy": briefing["prepared_by"] or "",
            "articles": evidence_input,
            "attemptLimit": 2,
            "contextLength": context_length,
        }
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
        cancel_token = CancellationToken()
        if not analysis_registry.register(run_id, briefing_id, cancel_token):
            connection.rollback()
            return error_response(
                "AI_ALREADY_RUNNING", "다른 AI 분석이 이미 실행 중입니다.", {"runId": analysis_registry.active_run_id()}
            )
        registered = True
        connection.commit()
    except Exception:
        connection.rollback()
        if registered:
            analysis_registry.unregister(run_id)
        raise
    finally:
        connection.close()

    try:
        worker = asyncio.create_task(
            asyncio.to_thread(
                analyze,
                client,
                model=body.model,
                report_date=report_date,
                prepared_by=prepared_by,
                evidence_input=evidence_input,
                evidence=evidence,
                cancel_token=cancel_token,
            )
        )
        deadline = time.monotonic() + ANALYSIS_TIMEOUT_SECONDS
        while not worker.done():
            await asyncio.wait({worker}, timeout=0.25)
            if worker.done():
                break
            if time.monotonic() >= deadline:
                cancel_token.cancel("timeout")
            elif await request.is_disconnected():
                cancel_token.cancel("client_disconnected")
        output = await worker
    except AnalysisCancelled as exc:
        if exc.reason == "timeout":
            code = "AI_TIMEOUT"
            stored_error = f"AI_TIMEOUT: {ANALYSIS_TIMEOUT_SECONDS}초 제한을 초과했습니다."
            message = f"AI 분석이 {ANALYSIS_TIMEOUT_SECONDS // 60}분 제한을 초과해 중단됐습니다."
        else:
            code = "AI_CANCELLED"
            stored_error = "AI_CANCELLED: 사용자가 분석을 취소했습니다."
            message = "AI 분석을 취소했습니다."
        connection = get_connection()
        try:
            with connection:
                ai_runs_repo.finish_failed(connection, run_id, stored_error)
        finally:
            connection.close()
        return _error_with_preserved_result(code, message, briefing_id, run_id)
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
    finally:
        analysis_registry.unregister(run_id)
        unload = getattr(client, "unload_model", None)
        if callable(unload):
            try:
                await asyncio.to_thread(unload, body.model)
            except (OllamaError, OSError, TimeoutError):
                pass

    connection = get_connection()
    try:
        current = briefings_repo.get_by_date(connection, report_date)
        current_input, _ = _inputs(connection, report_date)
        if (
            current is None
            or current["revision"] != body.expectedRevision
            or input_signature(body.model, current_input, context_length) != signature
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
        state = ai_state(connection, updated, body.model, context_length)
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
