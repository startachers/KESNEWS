from __future__ import annotations

import json
import sqlite3
from typing import Any

from backend.app.core.clock import now_iso
from backend.app.services.ids import make_id


def create(
    connection: sqlite3.Connection,
    *,
    report_date: str,
    input_signature: str,
    proposal: list[dict[str, Any]],
    diff: dict[str, Any],
    algorithm_version: str,
) -> sqlite3.Row:
    run_id = make_id()
    connection.execute(
        """
        INSERT INTO cluster_runs (
            id, report_date, status, input_signature, proposal_json, diff_json,
            algorithm_version, created_at
        ) VALUES (?, ?, 'proposed', ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            report_date,
            input_signature,
            json.dumps(proposal, ensure_ascii=False),
            json.dumps(diff, ensure_ascii=False),
            algorithm_version,
            now_iso(),
        ),
    )
    return get(connection, run_id)


def get(connection: sqlite3.Connection, run_id: str) -> sqlite3.Row | None:
    return connection.execute("SELECT * FROM cluster_runs WHERE id = ?", (run_id,)).fetchone()


def serialize(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "reportDate": row["report_date"],
        "status": row["status"],
        "inputSignature": row["input_signature"],
        "proposal": json.loads(row["proposal_json"]),
        "diff": json.loads(row["diff_json"]),
        "algorithmVersion": row["algorithm_version"],
        "createdAt": row["created_at"],
        "appliedAt": row["applied_at"],
    }


def mark_applied(connection: sqlite3.Connection, run_id: str) -> None:
    connection.execute(
        "UPDATE cluster_runs SET status = 'applied', applied_at = ? WHERE id = ?",
        (now_iso(), run_id),
    )
