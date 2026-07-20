from __future__ import annotations

import json
import sqlite3
from typing import Any

from backend.app.core.clock import now_iso


def get(connection: sqlite3.Connection, briefing_id: str) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT * FROM briefing_analysis_markdown WHERE briefing_id = ?", (briefing_id,)
    ).fetchone()


def upsert(
    connection: sqlite3.Connection,
    *,
    briefing_id: str,
    source_signature: str,
    input_signature: str,
    evidence: dict[str, str],
    file_hash: str,
    md_path: str,
) -> sqlite3.Row:
    now = now_iso()
    connection.execute(
        """
        INSERT INTO briefing_analysis_markdown (
            briefing_id, source_signature, input_signature, evidence_json,
            file_hash, md_path, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(briefing_id) DO UPDATE SET
            source_signature = excluded.source_signature,
            input_signature = excluded.input_signature,
            evidence_json = excluded.evidence_json,
            file_hash = excluded.file_hash,
            md_path = excluded.md_path,
            updated_at = excluded.updated_at
        """,
        (
            briefing_id,
            source_signature,
            input_signature,
            json.dumps(evidence, ensure_ascii=False, sort_keys=True),
            file_hash,
            md_path,
            now,
            now,
        ),
    )
    row = get(connection, briefing_id)
    assert row is not None
    return row


def evidence(row: sqlite3.Row) -> dict[str, str]:
    value: Any = json.loads(row["evidence_json"])
    return {str(key): str(article_id) for key, article_id in value.items()}
