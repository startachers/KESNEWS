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
        INSERT INTO ai_selection_runs (
            id, briefing_id, model, prompt_version, input_signature, status,
            request_json, response_json, evidence_json, error_message,
            started_at, finished_at, applied_at
        ) VALUES (?, ?, ?, ?, ?, 'running', ?, NULL, ?, NULL, ?, NULL, NULL)
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
    return connection.execute(
        "SELECT * FROM ai_selection_runs WHERE id = ?", (run_id,)
    ).fetchone()


def finish_success(
    connection: sqlite3.Connection, run_id: str, response: dict[str, Any]
) -> sqlite3.Row:
    connection.execute(
        """
        UPDATE ai_selection_runs
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
        UPDATE ai_selection_runs
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


def mark_applied(connection: sqlite3.Connection, run_id: str) -> sqlite3.Row:
    connection.execute(
        """
        UPDATE ai_selection_runs
        SET status = 'applied', applied_at = ?
        WHERE id = ? AND status = 'success'
        """,
        (now_iso(), run_id),
    )
    return get(connection, run_id)


def latest_success(connection: sqlite3.Connection, briefing_id: str) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT * FROM ai_selection_runs
        WHERE briefing_id = ? AND status IN ('success', 'applied')
        ORDER BY started_at DESC, id DESC LIMIT 1
        """,
        (briefing_id,),
    ).fetchone()


def latest_running(connection: sqlite3.Connection) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT * FROM ai_selection_runs
        WHERE status = 'running'
        ORDER BY started_at DESC, id DESC LIMIT 1
        """
    ).fetchone()


def fail_running(connection: sqlite3.Connection, error_message: str) -> int:
    cursor = connection.execute(
        """
        UPDATE ai_selection_runs
        SET status = 'failed', error_message = ?, finished_at = ?
        WHERE status = 'running'
        """,
        (error_message, now_iso()),
    )
    return cursor.rowcount


def serialize(row: sqlite3.Row | None) -> dict[str, Any] | None:
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
        "appliedAt": row["applied_at"],
    }
