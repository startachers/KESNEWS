from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response

from backend.app.api.envelope import error_response, ok_envelope
from backend.app.repositories import briefing_repository as briefing_repo
from backend.app.repositories import briefing_version_repository as version_repo
from backend.app.repositories.database import get_connection
from backend.app.services.exports import csv_export, json_export, markdown_export
from backend.app.services.analysis_markdown.service import GenerationError
from backend.app.services.analysis_markdown.service import generate as generate_analysis_markdown

router = APIRouter()


@router.post("/api/exports/{report_date}.md")
async def export_markdown(report_date: str) -> Any:
    connection = get_connection()
    try:
        briefing = briefing_repo.get_by_date(connection, report_date)
        if briefing is None:
            return error_response("BRIEFING_NOT_FOUND", f"{report_date} 작업본이 없습니다.")
    finally:
        connection.close()
    try:
        # 기존 수동 내보내기의 전문 refresh도 유지하되, 최종 판정·정제·서명·저장은
        # 테스트/향후 분석 버튼과 동일한 공통 생성 서비스를 사용한다.
        await asyncio.to_thread(markdown_export.refresh_selected_bodies, report_date, get_connection)
        output = await asyncio.to_thread(
            generate_analysis_markdown, get_connection, report_date, save=True
        )
    except GenerationError as exc:
        return error_response(exc.code, exc.message, {"failedArticles": exc.details})
    return Response(
        content=output.content.encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="KESCO_AI_{report_date}.md"',
            "X-KESCO-Input-Signature": output.result["inputSignature"],
            "X-KESCO-File-Hash": output.result["fileHash"],
        },
    )


@router.post("/api/briefings/{report_date}/analysis-markdown")
async def generate_markdown_result(report_date: str) -> Any:
    try:
        output = await asyncio.to_thread(
            generate_analysis_markdown, get_connection, report_date, save=True
        )
    except GenerationError as exc:
        return error_response(exc.code, exc.message, {"failedArticles": exc.details})
    return ok_envelope(output.result)


@router.get("/api/exports/{report_date}.json")
async def export_json(report_date: str, scope: str = Query("working")) -> Any:
    connection = get_connection()
    try:
        briefing = briefing_repo.get_by_date(connection, report_date)
        if briefing is None:
            data = None
        elif scope == "working":
            data = json_export.build_export(connection, report_date)
        else:
            row = _version_for_scope(connection, briefing["id"], scope)
            if row is None:
                return error_response("BRIEFING_VERSION_NOT_FOUND", "요청한 최종본이 없습니다.")
            data = json_export.build_version_export(row, report_date)
    finally:
        connection.close()
    if data is None:
        return error_response("BRIEFING_NOT_FOUND", f"{report_date} 작업본이 없습니다.")
    return ok_envelope(data)


@router.post("/api/exports/{report_date}.json")
async def import_json(report_date: str, request: Request, mode: str | None = Query(None)) -> Any:
    payload = await request.json()
    connection = get_connection()
    try:
        with connection:
            result = json_export.import_export(connection, report_date, payload, mode)
    except json_export.SchemaUnsupported:
        return error_response("IMPORT_SCHEMA_UNSUPPORTED", "지원하지 않는 schemaVersion입니다.")
    except json_export.ImportConflict as exc:
        return error_response(
            "IMPORT_CONFLICT",
            f"{report_date} 작업본이 이미 있습니다. mode=replace로 교체할 수 있습니다.",
            exc.details,
        )
    finally:
        connection.close()
    return ok_envelope(result)


@router.get("/api/exports/{report_date}.csv")
async def export_csv(report_date: str, scope: str = Query("working")) -> Any:
    connection = get_connection()
    try:
        briefing = briefing_repo.get_by_date(connection, report_date)
        if briefing is None:
            return error_response("BRIEFING_NOT_FOUND", f"{report_date} 작업본이 없습니다.")
        if scope == "working":
            csv_text = csv_export.build_csv(connection, report_date)
        else:
            row = _version_for_scope(connection, briefing["id"], scope)
            if row is None:
                return error_response("BRIEFING_VERSION_NOT_FOUND", "요청한 최종본이 없습니다.")
            snapshot = version_repo.serialize(row)["snapshot"]
            csv_text = csv_export.build_csv_from_articles(snapshot.get("articles") or [])
    finally:
        connection.close()
    return Response(
        content=csv_text.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="KESCO_{report_date}.csv"'},
    )


@router.post("/api/exports/{report_date}.csv")
async def import_csv(report_date: str, request: Request) -> Any:
    body = await request.json()
    csv_text = body.get("csv") or ""
    rows = csv_export.parse_csv(csv_text)
    connection = get_connection()
    try:
        with connection:
            result = csv_export.import_csv(connection, report_date, rows)
    except briefing_repo.BriefingNotFound:
        return error_response("BRIEFING_NOT_FOUND", f"{report_date} 작업본이 없습니다.")
    finally:
        connection.close()
    return ok_envelope(result)


def _version_for_scope(connection, briefing_id: str, scope: str):
    if scope == "latest-final":
        return version_repo.latest_version(connection, briefing_id)
    if scope.startswith("version:"):
        try:
            version = int(scope.split(":", 1)[1])
        except ValueError:
            return None
        return version_repo.get_version(connection, briefing_id, version)
    return None
