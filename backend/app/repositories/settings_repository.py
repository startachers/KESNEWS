from __future__ import annotations

import json
import sqlite3
from typing import Any

from backend.app.core.clock import now_iso

COLLECTION_SETTINGS_KEY = "collection"


def get_override(connection: sqlite3.Connection) -> tuple[dict[str, Any] | None, str | None]:
    row = connection.execute(
        "SELECT value_json, updated_at FROM settings WHERE key = ?",
        (COLLECTION_SETTINGS_KEY,),
    ).fetchone()
    if row is None:
        return None, None
    return json.loads(row["value_json"]), row["updated_at"]


def put_override(connection: sqlite3.Connection, value: dict[str, Any]) -> str:
    updated_at = now_iso()
    connection.execute(
        """
        INSERT INTO settings (key, value_json, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value_json = excluded.value_json,
            updated_at = excluded.updated_at
        """,
        (
            COLLECTION_SETTINGS_KEY,
            json.dumps(value, ensure_ascii=False, sort_keys=True),
            updated_at,
        ),
    )
    return updated_at


def delete_override(connection: sqlite3.Connection) -> bool:
    cursor = connection.execute(
        "DELETE FROM settings WHERE key = ?", (COLLECTION_SETTINGS_KEY,)
    )
    return cursor.rowcount > 0
