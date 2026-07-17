from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from backend.app.api.briefings import _serialize as serialize_briefing
from backend.app.api.envelope import error_response, ok_envelope
from backend.app.core.clock import today_seoul
from backend.app.repositories import briefing_repository as briefing_repo
from backend.app.repositories import weather_repository as weather_repo
from backend.app.repositories.database import get_connection
from backend.app.services.weather.collector import collect
from backend.app.services.weather.fallback import reuse_failed_providers

router = APIRouter()


class WeatherRefreshRequest(BaseModel):
    reportDate: str


class WeatherSignalSelection(BaseModel):
    id: str
    selected: bool = True
    editorLevel: Literal["critical", "watch", "info", "normal", "unknown"] | None = None
    editorNote: str = Field(default="", max_length=1000)


class WeatherBriefingRequest(BaseModel):
    expectedRevision: int
    contextId: str
    includeInReport: bool = True
    reviewStatus: Literal["pending", "reviewed"] = "reviewed"
    selectedSignals: list[WeatherSignalSelection] = Field(default_factory=list)
    editorNote: str = Field(default="", max_length=1000)


def _serialize_run(connection, row) -> dict[str, Any] | None:
    if row is None:
        return None
    providers = connection.execute(
        "SELECT * FROM weather_run_providers WHERE weather_collection_run_id = ?",
        (row["id"],),
    ).fetchall()
    return {
        "id": row["id"],
        "reportDate": row["report_date"],
        "startedAt": row["started_at"],
        "finishedAt": row["finished_at"],
        "status": row["status"],
        "contextId": row["context_id"],
        "warningCount": row["warning_count"],
        "errorCount": row["error_count"],
        "providers": [
            {
                "provider": item["provider"],
                "status": item["status"],
                "issuedAt": item["issued_at"],
                "fetchedAt": item["fetched_at"],
                "itemCount": item["item_count"],
                "errorCode": item["error_code"],
                "errorMessage": item["error_message"],
            }
            for item in providers
        ],
    }


def _latest_run(connection, report_date: str) -> dict[str, Any] | None:
    row = connection.execute(
        "SELECT * FROM weather_collection_runs WHERE report_date = ? "
        "ORDER BY started_at DESC LIMIT 1",
        (report_date,),
    ).fetchone()
    return _serialize_run(connection, row)


def _briefing_payload(connection, report_date: str) -> dict[str, Any]:
    briefing = briefing_repo.get_by_date(connection, report_date)
    latest_row = weather_repo.latest_context(connection, report_date)
    latest = weather_repo.serialize_context(connection, latest_row)
    attachment = (
        weather_repo.serialize_attachment(connection, briefing["id"])
        if briefing is not None
        else None
    )
    attached_context = None
    if attachment is not None:
        attached_context = weather_repo.serialize_context(
            connection, weather_repo.get_context(connection, attachment["contextId"])
        )
    return {
        "configured": bool(os.environ.get("KMA_SERVICE_KEY", "").strip()),
        "latestContext": latest,
        "attached": attachment,
        "attachedContext": attached_context,
        "newerContextAvailable": bool(
            latest
            and attachment
            and latest["id"] != attachment["contextId"]
        ),
        "latestRun": _latest_run(connection, report_date),
    }


@router.get("/api/weather/briefing")
async def get_weather_briefing(report_date: str = Query(...)) -> Any:
    connection = get_connection()
    try:
        payload = _briefing_payload(connection, report_date)
    finally:
        connection.close()
    return ok_envelope(payload)


@router.get("/api/weather/runs/{run_id}")
async def get_weather_run(run_id: str) -> Any:
    connection = get_connection()
    try:
        row = connection.execute(
            "SELECT * FROM weather_collection_runs WHERE id = ?", (run_id,)
        ).fetchone()
        payload = _serialize_run(connection, row)
    finally:
        connection.close()
    if payload is None:
        return error_response("WEATHER_RUN_NOT_FOUND", "기상정보 수집 실행을 찾을 수 없습니다.")
    return ok_envelope(payload)


@router.post("/api/weather/refresh")
async def refresh_weather(request: WeatherRefreshRequest) -> Any:
    if request.reportDate != today_seoul():
        return error_response(
            "WEATHER_TODAY_ONLY",
            "기상정보는 서울 기준 오늘 보고일만 새로 수집할 수 있습니다.",
        )
    service_key = os.environ.get("KMA_SERVICE_KEY", "").strip()
    if not service_key:
        return error_response(
            "WEATHER_NOT_CONFIGURED",
            ".env에 KMA_SERVICE_KEY를 설정한 뒤 서버를 다시 시작해 주세요.",
        )

    connection = get_connection()
    try:
        with connection:
            stale_cutoff = (
                datetime.now(timezone.utc) - timedelta(minutes=10)
            ).isoformat().replace("+00:00", "Z")
            weather_repo.expire_stale_runs(connection, stale_cutoff)
            running = connection.execute(
                "SELECT id FROM weather_collection_runs WHERE status = 'running' LIMIT 1"
            ).fetchone()
            if running is not None:
                return error_response(
                    "WEATHER_REFRESH_RUNNING", "기상정보를 이미 새로고침하고 있습니다."
                )
            run = weather_repo.create_run(connection, request.reportDate)
            previous_context = weather_repo.serialize_context(
                connection,
                weather_repo.latest_context(connection, request.reportDate),
            )
    finally:
        connection.close()

    try:
        result = await asyncio.to_thread(collect, service_key, request.reportDate)
        result = reuse_failed_providers(result, previous_context)
    except Exception as exc:
        connection = get_connection()
        try:
            with connection:
                weather_repo.finish_run(
                    connection,
                    run["id"],
                    status="failed",
                    context_id=None,
                    warning_count=0,
                    error_count=1,
                )
        finally:
            connection.close()
        return error_response("WEATHER_PROVIDER_FAILED", f"기상정보 수집에 실패했습니다: {exc}")

    successful = [item for item in result["providers"] if item["status"] != "failed"]
    errors = [item for item in result["providers"] if item["status"] != "success"]
    connection = get_connection()
    try:
        with connection:
            for provider in result["providers"]:
                provider_id = weather_repo.add_provider_result(
                    connection,
                    run["id"],
                    provider=provider["provider"],
                    status=provider["status"],
                    issued_at=provider.get("issuedAt"),
                    item_count=len(provider.get("items") or []),
                    error_code="WEATHER_PROVIDER_FAILED" if provider.get("error") else None,
                    error_message=provider.get("error"),
                )
                for observation in provider.get("observations") or []:
                    weather_repo.add_observation(
                        connection,
                        provider_id,
                        provider=observation["provider"],
                        product=observation["product"],
                        request_key=observation["requestKey"],
                        official_issued_at=observation.get("issuedAt"),
                        payload=observation["payload"],
                        payload_hash=observation["payloadHash"],
                    )
            context = None
            if successful or result.get("reusedProviders"):
                context = weather_repo.create_context(
                    connection,
                    report_date=request.reportDate,
                    period_from=result["periodFrom"],
                    period_to=result["periodTo"],
                    overall_level=result["overallLevel"],
                    issued_at=result["issuedAt"],
                    region_config_version=result["regionConfigVersion"],
                    risk_rule_version=result["riskRuleVersion"],
                    source_status=result["sourceStatus"],
                    days=result["days"],
                    alerts=result["alerts"],
                    input_signature=result["inputSignature"],
                    signals=result["signals"],
                )
            status = (
                "success"
                if not errors
                else "partial"
                if successful or result.get("reusedProviders")
                else "failed"
            )
            weather_repo.finish_run(
                connection,
                run["id"],
                status=status,
                context_id=context["id"] if context is not None else None,
                warning_count=len(result["signals"]),
                error_count=len(errors),
            )
            payload = _briefing_payload(connection, request.reportDate)
    finally:
        connection.close()
    return ok_envelope(payload)


@router.put("/api/briefings/{report_date}/weather")
async def put_briefing_weather(report_date: str, request: WeatherBriefingRequest) -> Any:
    connection = get_connection()
    try:
        with connection:
            updated = weather_repo.attach_context(
                connection,
                report_date=report_date,
                expected_revision=request.expectedRevision,
                context_id=request.contextId,
                include_in_report=request.includeInReport,
                review_status=request.reviewStatus,
                selected_signals=[item.model_dump() for item in request.selectedSignals],
                editor_note=request.editorNote,
            )
            payload = _briefing_payload(connection, report_date)
    except briefing_repo.BriefingNotFound:
        return error_response("BRIEFING_NOT_FOUND", f"{report_date} 작업본이 없습니다.")
    except briefing_repo.BriefingFinalized:
        return error_response("BRIEFING_FINALIZED", "최종 확정된 작업본은 수정할 수 없습니다.")
    except briefing_repo.RevisionConflict:
        return error_response("BRIEFING_REVISION_CONFLICT", "다른 화면에서 브리핑이 변경됐습니다.")
    except weather_repo.WeatherContextNotFound:
        return error_response("WEATHER_CONTEXT_NOT_FOUND", "보고일에 맞는 기상 컨텍스트가 없습니다.")
    except weather_repo.WeatherSignalInvalid:
        return error_response("WEATHER_SIGNAL_INVALID", "기상 컨텍스트에 없는 위험 신호입니다.")
    finally:
        connection.close()
    return ok_envelope(
        {"briefing": serialize_briefing(updated), "weather": payload},
        meta={"revision": updated["revision"]},
    )
