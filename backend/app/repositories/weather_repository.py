from __future__ import annotations

import json
import sqlite3
from typing import Any

from backend.app.core.clock import now_iso
from backend.app.repositories import briefing_repository as briefing_repo
from backend.app.services.ids import make_id


class WeatherContextNotFound(Exception):
    pass


class WeatherSignalInvalid(Exception):
    pass


def _loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def create_run(connection: sqlite3.Connection, report_date: str) -> sqlite3.Row:
    run_id = make_id()
    now = now_iso()
    connection.execute(
        """
        INSERT INTO weather_collection_runs (
            id, report_date, started_at, status, created_at
        ) VALUES (?, ?, ?, 'running', ?)
        """,
        (run_id, report_date, now, now),
    )
    return connection.execute(
        "SELECT * FROM weather_collection_runs WHERE id = ?", (run_id,)
    ).fetchone()


def expire_stale_runs(connection: sqlite3.Connection, cutoff: str) -> int:
    """비정상 종료로 남은 running 행을 명시적 실패 상태로 전환한다."""
    cursor = connection.execute(
        """
        UPDATE weather_collection_runs
        SET finished_at = ?, status = 'failed', error_count = MAX(error_count, 1)
        WHERE status = 'running' AND started_at < ?
        """,
        (now_iso(), cutoff),
    )
    return cursor.rowcount


def add_provider_result(
    connection: sqlite3.Connection,
    run_id: str,
    *,
    provider: str,
    status: str,
    issued_at: str | None,
    item_count: int,
    error_code: str | None = None,
    error_message: str | None = None,
) -> str:
    provider_id = make_id()
    connection.execute(
        """
        INSERT INTO weather_run_providers (
            id, weather_collection_run_id, provider, status, issued_at, fetched_at,
            item_count, error_code, error_message
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            provider_id,
            run_id,
            provider,
            status,
            issued_at,
            now_iso(),
            item_count,
            error_code,
            error_message,
        ),
    )
    return provider_id


def add_observation(
    connection: sqlite3.Connection,
    provider_result_id: str,
    *,
    provider: str,
    product: str,
    request_key: str,
    official_issued_at: str | None,
    payload: Any,
    payload_hash: str,
) -> str:
    observation_id = make_id()
    connection.execute(
        """
        INSERT INTO weather_observations (
            id, weather_run_provider_id, provider, product, request_key,
            official_issued_at, observed_at, payload_json, payload_hash
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            observation_id,
            provider_result_id,
            provider,
            product,
            request_key,
            official_issued_at,
            now_iso(),
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            payload_hash,
        ),
    )
    return observation_id


def create_context(
    connection: sqlite3.Connection,
    *,
    report_date: str,
    period_from: str,
    period_to: str,
    overall_level: str,
    issued_at: str | None,
    region_config_version: str,
    risk_rule_version: str,
    source_status: dict[str, Any],
    days: list[dict[str, Any]],
    alerts: list[dict[str, Any]],
    input_signature: str,
    signals: list[dict[str, Any]],
) -> sqlite3.Row:
    existing = connection.execute(
        "SELECT * FROM weather_contexts WHERE report_date = ? AND input_signature = ?",
        (report_date, input_signature),
    ).fetchone()
    if existing is not None:
        return existing
    context_id = make_id()
    now = now_iso()
    connection.execute(
        """
        INSERT INTO weather_contexts (
            id, report_date, period_from, period_to, overall_level, issued_at,
            built_at, region_config_version, risk_rule_version, source_status_json,
            daily_summaries_json, alerts_json, input_signature, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            context_id,
            report_date,
            period_from,
            period_to,
            overall_level,
            issued_at,
            now,
            region_config_version,
            risk_rule_version,
            json.dumps(source_status, ensure_ascii=False, separators=(",", ":")),
            json.dumps(days, ensure_ascii=False, separators=(",", ":")),
            json.dumps(alerts, ensure_ascii=False, separators=(",", ":")),
            input_signature,
            now,
        ),
    )
    for signal in signals:
        connection.execute(
            """
            INSERT INTO weather_risk_signals (
                id, weather_context_id, signal_key, hazard, level, starts_at, ends_at,
                region_ids_json, electrical_risks_json, recommended_checks_json,
                evidence_json, confidence, rule_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                signal.get("id") or make_id(),
                context_id,
                signal["signalKey"],
                signal["hazard"],
                signal["level"],
                signal.get("startsAt"),
                signal.get("endsAt"),
                json.dumps(signal.get("regionIds") or [], ensure_ascii=False),
                json.dumps(signal.get("electricalRisks") or [], ensure_ascii=False),
                json.dumps(signal.get("recommendedChecks") or [], ensure_ascii=False),
                json.dumps(signal.get("evidence") or [], ensure_ascii=False),
                signal.get("confidence") or "high",
                signal.get("ruleId") or "official-alert-v1",
                now,
            ),
        )
    return connection.execute(
        "SELECT * FROM weather_contexts WHERE id = ?", (context_id,)
    ).fetchone()


def finish_run(
    connection: sqlite3.Connection,
    run_id: str,
    *,
    status: str,
    context_id: str | None,
    warning_count: int,
    error_count: int,
) -> sqlite3.Row:
    connection.execute(
        """
        UPDATE weather_collection_runs
        SET finished_at = ?, status = ?, context_id = ?, warning_count = ?, error_count = ?
        WHERE id = ?
        """,
        (now_iso(), status, context_id, warning_count, error_count, run_id),
    )
    return connection.execute(
        "SELECT * FROM weather_collection_runs WHERE id = ?", (run_id,)
    ).fetchone()


def list_signals(connection: sqlite3.Connection, context_id: str) -> list[dict[str, Any]]:
    rows = connection.execute(
        "SELECT * FROM weather_risk_signals WHERE weather_context_id = ? "
        "ORDER BY CASE level WHEN 'critical' THEN 0 WHEN 'watch' THEN 1 ELSE 2 END, starts_at",
        (context_id,),
    ).fetchall()
    return [
        {
            "id": row["id"],
            "signalKey": row["signal_key"],
            "hazard": row["hazard"],
            "level": row["level"],
            "startsAt": row["starts_at"],
            "endsAt": row["ends_at"],
            "regionIds": _loads(row["region_ids_json"], []),
            "electricalRisks": _loads(row["electrical_risks_json"], []),
            "recommendedChecks": _loads(row["recommended_checks_json"], []),
            "evidence": _loads(row["evidence_json"], []),
            "confidence": row["confidence"],
            "ruleId": row["rule_id"],
        }
        for row in rows
    ]


def serialize_context(connection: sqlite3.Connection, row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row["id"],
        "reportDate": row["report_date"],
        "period": {"from": row["period_from"], "to": row["period_to"]},
        "overallLevel": row["overall_level"],
        "issuedAt": row["issued_at"],
        "builtAt": row["built_at"],
        "regionConfigVersion": row["region_config_version"],
        "riskRuleVersion": row["risk_rule_version"],
        "sourceStatus": _loads(row["source_status_json"], {}),
        "days": _loads(row["daily_summaries_json"], []),
        "alerts": _loads(row["alerts_json"], []),
        "inputSignature": row["input_signature"],
        "riskSignals": list_signals(connection, row["id"]),
    }


def latest_context(connection: sqlite3.Connection, report_date: str) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT * FROM weather_contexts WHERE report_date = ? ORDER BY built_at DESC LIMIT 1",
        (report_date,),
    ).fetchone()


def get_context(connection: sqlite3.Connection, context_id: str) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT * FROM weather_contexts WHERE id = ?", (context_id,)
    ).fetchone()


def get_attachment(connection: sqlite3.Connection, briefing_id: str) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT * FROM briefing_weather WHERE briefing_id = ?", (briefing_id,)
    ).fetchone()


def serialize_attachment(connection: sqlite3.Connection, briefing_id: str) -> dict[str, Any] | None:
    row = get_attachment(connection, briefing_id)
    if row is None:
        return None
    selected_rows = connection.execute(
        """
        SELECT weather_risk_signal_id, selected, editor_level, editor_note
        FROM briefing_weather_signals WHERE briefing_id = ?
        """,
        (briefing_id,),
    ).fetchall()
    return {
        "contextId": row["weather_context_id"],
        "includeInReport": bool(row["include_in_report"]),
        "reviewStatus": row["review_status"],
        "editorNote": row["editor_note"] or "",
        "attachedAt": row["attached_at"],
        "reviewedAt": row["reviewed_at"],
        "signals": [
            {
                "id": item["weather_risk_signal_id"],
                "selected": bool(item["selected"]),
                "editorLevel": item["editor_level"],
                "editorNote": item["editor_note"] or "",
            }
            for item in selected_rows
        ],
    }


def attach_context(
    connection: sqlite3.Connection,
    *,
    report_date: str,
    expected_revision: int,
    context_id: str,
    include_in_report: bool,
    review_status: str,
    selected_signals: list[dict[str, Any]],
    editor_note: str,
) -> sqlite3.Row:
    briefing = briefing_repo.get_by_date(connection, report_date)
    if briefing is None:
        raise briefing_repo.BriefingNotFound()
    if briefing["status"] == "final":
        raise briefing_repo.BriefingFinalized()
    if briefing["revision"] != expected_revision:
        raise briefing_repo.RevisionConflict()
    context = get_context(connection, context_id)
    if context is None or context["report_date"] != report_date:
        raise WeatherContextNotFound()
    valid_ids = {item["id"] for item in list_signals(connection, context_id)}
    selections = {item["id"]: item for item in selected_signals}
    if not set(selections).issubset(valid_ids):
        raise WeatherSignalInvalid()

    now = now_iso()
    reviewed_at = now if review_status == "reviewed" else None
    connection.execute(
        """
        INSERT INTO briefing_weather (
            briefing_id, weather_context_id, include_in_report, review_status,
            editor_note, attached_at, reviewed_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(briefing_id) DO UPDATE SET
            weather_context_id = excluded.weather_context_id,
            include_in_report = excluded.include_in_report,
            review_status = excluded.review_status,
            editor_note = excluded.editor_note,
            attached_at = excluded.attached_at,
            reviewed_at = excluded.reviewed_at,
            updated_at = excluded.updated_at
        """,
        (
            briefing["id"],
            context_id,
            int(include_in_report),
            review_status,
            editor_note,
            now,
            reviewed_at,
            now,
        ),
    )
    connection.execute(
        "DELETE FROM briefing_weather_signals WHERE briefing_id = ? AND weather_context_id != ?",
        (briefing["id"], context_id),
    )
    for signal_id in valid_ids:
        selection = selections.get(signal_id)
        existing_signal = connection.execute(
            "SELECT * FROM briefing_weather_signals WHERE briefing_id = ? AND weather_risk_signal_id = ?",
            (briefing["id"], signal_id),
        ).fetchone()
        selected = (
            bool(selection["selected"])
            if selection is not None
            else bool(existing_signal["selected"])
            if existing_signal is not None
            else False
        )
        editor_level = (
            selection.get("editorLevel")
            if selection is not None
            else existing_signal["editor_level"]
            if existing_signal is not None
            else None
        )
        signal_note = (
            selection.get("editorNote") or ""
            if selection is not None
            else existing_signal["editor_note"] or ""
            if existing_signal is not None
            else ""
        )
        connection.execute(
            """
            INSERT INTO briefing_weather_signals (
                briefing_id, weather_context_id, weather_risk_signal_id, selected,
                editor_level, editor_note, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(briefing_id, weather_risk_signal_id) DO UPDATE SET
                selected = excluded.selected,
                editor_level = excluded.editor_level,
                editor_note = excluded.editor_note,
                updated_at = excluded.updated_at
            """,
            (
                briefing["id"],
                context_id,
                signal_id,
                int(selected),
                editor_level,
                signal_note,
                now,
                now,
            ),
        )
    row = connection.execute(
        """
        UPDATE briefings SET revision = revision + 1, updated_at = ?
        WHERE id = ? AND revision = ? RETURNING *
        """,
        (now, briefing["id"], expected_revision),
    ).fetchone()
    if row is None:
        raise briefing_repo.RevisionConflict()
    return row


def snapshot_for_briefing(
    connection: sqlite3.Connection, briefing_id: str
) -> dict[str, Any] | None:
    attachment = serialize_attachment(connection, briefing_id)
    if attachment is None or not attachment["includeInReport"]:
        return None
    context_row = get_context(connection, attachment["contextId"])
    context = serialize_context(connection, context_row)
    if context is None:
        return None
    overrides = {item["id"]: item for item in attachment["signals"]}
    selected_signals = []
    for item in context["riskSignals"]:
        override = overrides.get(item["id"])
        if override is None or not override["selected"]:
            continue
        selected_signals.append(
            {
                **item,
                "autoLevel": item["level"],
                "level": override.get("editorLevel") or item["level"],
                "editorNote": override.get("editorNote") or "",
            }
        )
    context["riskSignals"] = selected_signals
    return {"attachment": attachment, "context": context}


def export_for_briefing(
    connection: sqlite3.Connection, briefing_id: str
) -> dict[str, Any] | None:
    attachment = serialize_attachment(connection, briefing_id)
    if attachment is None:
        return None
    context = serialize_context(
        connection, get_context(connection, attachment["contextId"])
    )
    return {"attachment": attachment, "context": context}
