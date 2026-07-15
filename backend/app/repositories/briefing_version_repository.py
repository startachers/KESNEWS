from __future__ import annotations

import json
import sqlite3
from typing import Any

from backend.app.core.clock import now_iso
from backend.app.services.ids import make_id


class VersionNotFound(Exception):
    pass


def list_versions(connection: sqlite3.Connection, briefing_id: str) -> list[sqlite3.Row]:
    return connection.execute(
        "SELECT * FROM briefing_versions WHERE briefing_id = ? ORDER BY version DESC",
        (briefing_id,),
    ).fetchall()


def get_version(connection: sqlite3.Connection, briefing_id: str, version: int) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT * FROM briefing_versions WHERE briefing_id = ? AND version = ?",
        (briefing_id, version),
    ).fetchone()


def latest_version(connection: sqlite3.Connection, briefing_id: str) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT * FROM briefing_versions WHERE briefing_id = ? ORDER BY version DESC LIMIT 1",
        (briefing_id,),
    ).fetchone()


def next_version(connection: sqlite3.Connection, briefing_id: str) -> int:
    row = connection.execute(
        "SELECT COALESCE(MAX(version), 0) + 1 AS version FROM briefing_versions WHERE briefing_id = ?",
        (briefing_id,),
    ).fetchone()
    return int(row["version"])


def create(
    connection: sqlite3.Connection,
    *,
    briefing_id: str,
    version: int,
    source_revision: int,
    snapshot: dict[str, Any],
    report_html_path: str,
    finalized_at: str,
) -> sqlite3.Row:
    version_id = make_id()
    connection.execute(
        """
        INSERT INTO briefing_versions (
            id, briefing_id, version, source_revision, snapshot_json,
            report_html_path, finalized_at, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            version_id,
            briefing_id,
            version,
            source_revision,
            json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
            report_html_path,
            finalized_at,
            now_iso(),
        ),
    )
    return get_version(connection, briefing_id, version)


def import_version(
    connection: sqlite3.Connection,
    *,
    briefing_id: str,
    version: int,
    source_revision: int | None,
    snapshot: dict[str, Any],
    finalized_at: str | None,
    report_html_path: str | None = None,
) -> sqlite3.Row:
    version_id = make_id()
    created_at = finalized_at or now_iso()
    connection.execute(
        """
        INSERT INTO briefing_versions (
            id, briefing_id, version, source_revision, snapshot_json,
            report_html_path, finalized_at, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            version_id,
            briefing_id,
            version,
            source_revision,
            json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
            report_html_path,
            finalized_at,
            created_at,
        ),
    )
    return get_version(connection, briefing_id, version)


def serialize(row: sqlite3.Row, *, include_snapshot: bool = True) -> dict[str, Any]:
    data = {
        "id": row["id"],
        "version": row["version"],
        "sourceRevision": row["source_revision"],
        "reportHtmlPath": row["report_html_path"],
        "finalizedAt": row["finalized_at"],
        "createdAt": row["created_at"],
    }
    if include_snapshot:
        data["snapshot"] = json.loads(row["snapshot_json"])
    return data
