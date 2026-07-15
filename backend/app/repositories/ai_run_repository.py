from __future__ import annotations

import json
import sqlite3
from typing import Any

from backend.app.core.clock import now_iso
from backend.app.services.ids import make_id


def create(
    connection: sqlite3.Connection,
    *,
    briefing_id: str,
    model: str,
    prompt_version: str,
    input_signature: str,
    request: dict[str, Any],
    evidence: dict[str, str],
) -> sqlite3.Row:
    run_id = make_id()
    connection.execute(
        """
        INSERT INTO ai_runs (
            id, briefing_id, model, prompt_version, input_signature, status,
            request_json, response_json, evidence_json, error_message, started_at, finished_at
        ) VALUES (?, ?, ?, ?, ?, 'running', ?, NULL, ?, NULL, ?, NULL)
        """,
        (
            run_id,
            briefing_id,
            model,
            prompt_version,
            input_signature,
            json.dumps(request, ensure_ascii=False),
            json.dumps(evidence, ensure_ascii=False),
            now_iso(),
        ),
    )
    return get(connection, run_id)


def get(connection: sqlite3.Connection, run_id: str) -> sqlite3.Row | None:
    return connection.execute("SELECT * FROM ai_runs WHERE id = ?", (run_id,)).fetchone()


def finish_success(
    connection: sqlite3.Connection, run_id: str, response: dict[str, Any]
) -> sqlite3.Row:
    connection.execute(
        """
        UPDATE ai_runs
        SET status = 'success', response_json = ?, error_message = NULL, finished_at = ?
        WHERE id = ?
        """,
        (json.dumps(response, ensure_ascii=False), now_iso(), run_id),
    )
    return get(connection, run_id)


def finish_failed(
    connection: sqlite3.Connection,
    run_id: str,
    error_message: str,
    response: dict[str, Any] | None = None,
) -> sqlite3.Row:
    connection.execute(
        """
        UPDATE ai_runs
        SET status = 'failed', response_json = ?, error_message = ?, finished_at = ?
        WHERE id = ?
        """,
        (
            json.dumps(response, ensure_ascii=False) if response is not None else None,
            error_message,
            now_iso(),
            run_id,
        ),
    )
    return get(connection, run_id)


def latest(connection: sqlite3.Connection, briefing_id: str) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT * FROM ai_runs WHERE briefing_id = ? ORDER BY started_at DESC, id DESC LIMIT 1",
        (briefing_id,),
    ).fetchone()


def latest_success(connection: sqlite3.Connection, briefing_id: str) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT * FROM ai_runs
        WHERE briefing_id = ? AND status = 'success'
        ORDER BY started_at DESC, id DESC LIMIT 1
        """,
        (briefing_id,),
    ).fetchone()


def latest_running(connection: sqlite3.Connection) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT * FROM ai_runs WHERE status = 'running' ORDER BY started_at DESC, id DESC LIMIT 1"
    ).fetchone()


def fail_running(connection: sqlite3.Connection, error_message: str) -> int:
    cursor = connection.execute(
        """
        UPDATE ai_runs
        SET status = 'failed', error_message = ?, finished_at = ?
        WHERE status = 'running'
        """,
        (error_message, now_iso()),
    )
    return cursor.rowcount


def list_for_briefing(connection: sqlite3.Connection, briefing_id: str) -> list[sqlite3.Row]:
    return connection.execute(
        "SELECT * FROM ai_runs WHERE briefing_id = ? ORDER BY started_at, id", (briefing_id,)
    ).fetchall()


def serialize(row: sqlite3.Row | None, *, stale: bool = False) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row["id"],
        "model": row["model"],
        "promptVersion": row["prompt_version"],
        "inputSignature": row["input_signature"],
        "status": row["status"],
        "request": json.loads(row["request_json"]),
        "response": json.loads(row["response_json"]) if row["response_json"] else None,
        "evidence": json.loads(row["evidence_json"]),
        "errorMessage": row["error_message"],
        "startedAt": row["started_at"],
        "finishedAt": row["finished_at"],
        "stale": stale,
    }


def import_runs(
    connection: sqlite3.Connection,
    briefing_id: str,
    runs: list[dict[str, Any]],
    article_id_map: dict[str, str],
) -> int:
    imported = 0
    for item in runs:
        evidence = {
            evidence_id: article_id_map.get(article_id, article_id)
            for evidence_id, article_id in (item.get("evidence") or {}).items()
        }
        connection.execute(
            """
            INSERT INTO ai_runs (
                id, briefing_id, model, prompt_version, input_signature, status,
                request_json, response_json, evidence_json, error_message, started_at, finished_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                make_id(),
                briefing_id,
                item.get("model") or "unknown",
                item.get("promptVersion") or "imported",
                item.get("inputSignature") or "imported",
                item.get("status") if item.get("status") in {"running", "success", "failed"} else "failed",
                json.dumps(item.get("request") or {}, ensure_ascii=False),
                json.dumps(item.get("response"), ensure_ascii=False) if item.get("response") is not None else None,
                json.dumps(evidence, ensure_ascii=False),
                item.get("errorMessage"),
                item.get("startedAt") or now_iso(),
                item.get("finishedAt"),
            ),
        )
        imported += 1
    return imported
