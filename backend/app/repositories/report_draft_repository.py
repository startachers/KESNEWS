from __future__ import annotations

import json
import sqlite3
from typing import Any

from backend.app.core.clock import now_iso


def get(connection: sqlite3.Connection, briefing_id: str) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT * FROM briefing_report_drafts WHERE briefing_id = ?", (briefing_id,)
    ).fetchone()


def upsert(
    connection: sqlite3.Connection,
    *,
    briefing_id: str,
    source_type: str,
    source_label: str,
    content: dict[str, Any],
    evidence: dict[str, str],
    input_signature: str,
    based_on_ai_run_id: str | None,
) -> sqlite3.Row:
    now = now_iso()
    connection.execute(
        """
        INSERT INTO briefing_report_drafts (
            briefing_id, source_type, source_label, content_json, evidence_json,
            input_signature, based_on_ai_run_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(briefing_id) DO UPDATE SET
            source_type = excluded.source_type,
            source_label = excluded.source_label,
            content_json = excluded.content_json,
            evidence_json = excluded.evidence_json,
            input_signature = excluded.input_signature,
            based_on_ai_run_id = excluded.based_on_ai_run_id,
            updated_at = excluded.updated_at
        """,
        (
            briefing_id,
            source_type,
            source_label or None,
            json.dumps(content, ensure_ascii=False),
            json.dumps(evidence, ensure_ascii=False),
            input_signature,
            based_on_ai_run_id,
            now,
            now,
        ),
    )
    row = get(connection, briefing_id)
    assert row is not None
    return row


def serialize(row: sqlite3.Row | None, *, stale: bool = False) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "sourceType": row["source_type"],
        "sourceLabel": row["source_label"] or "",
        "content": json.loads(row["content_json"]),
        "evidence": json.loads(row["evidence_json"]),
        "inputSignature": row["input_signature"],
        "basedOnAiRunId": row["based_on_ai_run_id"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "stale": stale,
    }
