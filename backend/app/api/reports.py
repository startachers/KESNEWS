from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import asyncio
from uuid import uuid4

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from backend.app.api.briefings import _serialize
from backend.app.api.envelope import error_response, ok_envelope
from backend.app.core.clock import now_iso
from backend.app.repositories import briefing_repository as briefing_repo
from backend.app.repositories import briefing_version_repository as version_repo
from backend.app.repositories import weather_repository as weather_repo
from backend.app.repositories.database import backup_database, get_connection
from backend.app.services.exports.json_export import build_version_export
from backend.app.services.ai.article_summarizer import ArticleSummaryError, summarize_articles
from backend.app.services.ai.ollama_client import OllamaError, default_client
from backend.app.services.ai.runtime import CancellationToken, analysis_registry
from backend.app.services.reports.renderer import render_report
from backend.app.services.reports.renderer import _article_body_preview, _article_source_label
from backend.app.services.reports.snapshot import build_snapshot
from backend.app.services.reports.storage import write_report, write_snapshot_backup

router = APIRouter()


class RevisionRequest(BaseModel):
    expectedRevision: int


class ArticleSummaryRequest(BaseModel):
    model: str


def _briefing_error(exc: Exception, report_date: str):
    if isinstance(exc, briefing_repo.BriefingNotFound):
        return error_response("BRIEFING_NOT_FOUND", f"{report_date} 작업본이 없습니다.")
    if isinstance(exc, briefing_repo.BriefingFinalized):
        return error_response("BRIEFING_FINALIZED", "이미 최종 확정된 작업본입니다.")
    return error_response("BRIEFING_REVISION_CONFLICT", "다른 화면에서 브리핑이 변경됐습니다.")


@router.get("/api/briefings/{report_date}/versions")
async def list_briefing_versions(report_date: str) -> Any:
    connection = get_connection()
    try:
        briefing = briefing_repo.get_by_date(connection, report_date)
        if briefing is None:
            return error_response("BRIEFING_NOT_FOUND", f"{report_date} 작업본이 없습니다.")
        versions = [
            version_repo.serialize(row, include_snapshot=False)
            for row in version_repo.list_versions(connection, briefing["id"])
        ]
    finally:
        connection.close()
    return ok_envelope({"versions": versions})


@router.get("/api/briefings/{report_date}/versions/{version}")
async def get_briefing_version(report_date: str, version: int) -> Any:
    connection = get_connection()
    try:
        briefing = briefing_repo.get_by_date(connection, report_date)
        if briefing is None:
            return error_response("BRIEFING_NOT_FOUND", f"{report_date} 작업본이 없습니다.")
        row = version_repo.get_version(connection, briefing["id"], version)
    finally:
        connection.close()
    if row is None:
        return error_response("BRIEFING_VERSION_NOT_FOUND", f"최종본 v{version}이 없습니다.")
    return ok_envelope(version_repo.serialize(row))


@router.post("/api/briefings/{report_date}/finalize")
async def finalize_briefing(report_date: str, request: RevisionRequest) -> Any:
    connection = get_connection()
    written_path: Path | None = None
    snapshot_path: Path | None = None
    try:
        briefing = briefing_repo.get_by_date(connection, report_date)
        if briefing is None:
            return error_response("BRIEFING_NOT_FOUND", f"{report_date} 작업본이 없습니다.")
        if briefing["status"] == "final":
            return error_response("BRIEFING_FINALIZED", "이미 최종 확정된 작업본입니다.")
        if briefing["revision"] != request.expectedRevision:
            return error_response(
                "BRIEFING_REVISION_CONFLICT", "다른 화면에서 브리핑이 변경됐습니다."
            )
        weather_attachment = weather_repo.get_attachment(connection, briefing["id"])
        if (
            weather_attachment is not None
            and weather_attachment["include_in_report"]
            and weather_attachment["review_status"] != "reviewed"
        ):
            return error_response(
                "WEATHER_REVIEW_REQUIRED",
                "CEO 보고에 포함할 기상정보를 검토 완료해 주세요.",
            )
        backup_database()
        with connection:
            version = version_repo.next_version(connection, briefing["id"])
            finalized_at = now_iso()
            snapshot = build_snapshot(
                connection, briefing, version=version, finalized_at=finalized_at
            )
            html = render_report(snapshot)
            written_path = write_report(report_date, version, html)
            version_row = version_repo.create(
                connection,
                briefing_id=briefing["id"],
                version=version,
                source_revision=request.expectedRevision,
                snapshot=snapshot,
                report_html_path=str(written_path),
                finalized_at=finalized_at,
            )
            snapshot_path = write_snapshot_backup(
                report_date, version, build_version_export(version_row, report_date)
            )
            updated = briefing_repo.finalize(
                connection,
                briefing["id"],
                request.expectedRevision,
                version,
                finalized_at,
            )
    except (
        briefing_repo.BriefingNotFound,
        briefing_repo.BriefingFinalized,
        briefing_repo.RevisionConflict,
    ) as exc:
        if written_path is not None:
            written_path.unlink(missing_ok=True)
        if snapshot_path is not None:
            snapshot_path.unlink(missing_ok=True)
        return _briefing_error(exc, report_date)
    except Exception:
        if written_path is not None:
            written_path.unlink(missing_ok=True)
        if snapshot_path is not None:
            snapshot_path.unlink(missing_ok=True)
        raise
    finally:
        connection.close()
    data = version_repo.serialize(version_row, include_snapshot=False)
    data["briefing"] = _serialize(updated)
    return ok_envelope(data, meta={"revision": updated["revision"]})


@router.post("/api/briefings/{report_date}/reopen")
async def reopen_briefing(report_date: str, request: RevisionRequest) -> Any:
    connection = get_connection()
    try:
        with connection:
            updated = briefing_repo.reopen(connection, report_date, request.expectedRevision)
    except (briefing_repo.BriefingNotFound, briefing_repo.RevisionConflict) as exc:
        return _briefing_error(exc, report_date)
    finally:
        connection.close()
    return ok_envelope(_serialize(updated), meta={"revision": updated["revision"]})


@router.get("/preview/{report_date}", response_class=HTMLResponse)
async def preview_report(report_date: str):
    connection = get_connection()
    try:
        briefing = briefing_repo.get_by_date(connection, report_date)
        if briefing is None:
            return HTMLResponse(f"{report_date} 작업본이 없습니다.", status_code=404)
        snapshot = build_snapshot(connection, briefing, version=None, finalized_at=None)
    finally:
        connection.close()
    return HTMLResponse(render_report(snapshot, preview=True))


@router.post("/api/briefings/{report_date}/article-summaries")
async def summarize_preview_articles(
    report_date: str, body: ArticleSummaryRequest, request: Request
) -> Any:
    connection = get_connection()
    try:
        briefing = briefing_repo.get_by_date(connection, report_date)
        if briefing is None:
            return error_response("BRIEFING_NOT_FOUND", f"{report_date} 작업본이 없습니다.")
        snapshot = build_snapshot(connection, briefing, version=None, finalized_at=None)
        source_revision = briefing["revision"]
    finally:
        connection.close()

    articles = [
        {
            "articleId": str(item.get("id") or ""),
            "title": str(item.get("title") or ""),
            "source": _article_source_label(item),
            "content": _article_body_preview(item),
        }
        for item in snapshot.get("articles") or []
        if item.get("id")
    ]
    if not articles:
        return error_response("AI_SCHEMA_INVALID", "요약할 선정 기사가 없습니다.")

    run_id = f"preview-summary-{uuid4().hex}"
    cancel_token = CancellationToken()
    if not analysis_registry.register(run_id, briefing["id"], cancel_token):
        return error_response(
            "AI_ALREADY_RUNNING",
            "다른 AI 분석이 이미 실행 중입니다. 완료하거나 취소한 뒤 다시 시도해 주세요.",
            {"runId": analysis_registry.active_run_id()},
        )
    client = getattr(request.app.state, "ollama_client", default_client)
    try:
        summaries = await asyncio.to_thread(
            summarize_articles,
            client,
            model=body.model,
            articles=articles,
            cancel_token=cancel_token,
        )
    except ArticleSummaryError as exc:
        return error_response("AI_SCHEMA_INVALID", str(exc))
    except (OllamaError, OSError, TimeoutError):
        return error_response("AI_UNAVAILABLE", "Ollama에 연결할 수 없습니다.")
    finally:
        analysis_registry.unregister(run_id)
        unload = getattr(client, "unload_model", None)
        if callable(unload):
            try:
                await asyncio.to_thread(unload, body.model)
            except (OllamaError, OSError, TimeoutError):
                pass

    return ok_envelope(
        {"summaries": summaries, "model": body.model, "sourceRevision": source_revision}
    )


@router.get("/report/{report_date}", response_class=HTMLResponse)
async def final_report(report_date: str, version: int | None = Query(None)):
    connection = get_connection()
    try:
        briefing = briefing_repo.get_by_date(connection, report_date)
        if briefing is None:
            return HTMLResponse(f"{report_date} 최종본이 없습니다.", status_code=404)
        row = (
            version_repo.get_version(connection, briefing["id"], version)
            if version is not None
            else version_repo.latest_version(connection, briefing["id"])
        )
    finally:
        connection.close()
    if row is None:
        return HTMLResponse(f"{report_date} 최종본이 없습니다.", status_code=404)
    path = Path(row["report_html_path"]) if row["report_html_path"] else None
    if path is not None and path.is_file():
        return HTMLResponse(path.read_text(encoding="utf-8"))
    return HTMLResponse(render_report(json.loads(row["snapshot_json"])))
