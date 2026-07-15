from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response

from backend.app.api.envelope import error_response, ok_envelope
from backend.app.repositories import briefing_repository as briefing_repo
from backend.app.repositories.database import get_connection
from backend.app.services.exports import csv_export, json_export

router = APIRouter()


@router.get("/api/exports/{report_date}.json")
async def export_json(report_date: str) -> Any:
    connection = get_connection()
    try:
        data = json_export.build_export(connection, report_date)
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
async def export_csv(report_date: str) -> Any:
    connection = get_connection()
    try:
        briefing = briefing_repo.get_by_date(connection, report_date)
        if briefing is None:
            return error_response("BRIEFING_NOT_FOUND", f"{report_date} 작업본이 없습니다.")
        csv_text = csv_export.build_csv(connection, report_date)
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
