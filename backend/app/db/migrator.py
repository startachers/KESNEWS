from __future__ import annotations

import sqlite3
from pathlib import Path

from backend.app.core.clock import now_iso

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

_BOOTSTRAP_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    id TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL
)
"""


def pending_migrations(connection: sqlite3.Connection) -> list[Path]:
    connection.execute(_BOOTSTRAP_SQL)
    applied = {row[0] for row in connection.execute("SELECT id FROM schema_migrations")}
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    return [path for path in files if path.name not in applied]


def apply_migrations(connection: sqlite3.Connection) -> list[str]:
    """대기 중인 migration을 파일명 순으로 적용한다. 이미 적용된 항목은 건너뛴다(idempotent)."""
    to_apply = pending_migrations(connection)
    applied_ids: list[str] = []
    for path in to_apply:
        script = path.read_text(encoding="utf-8")
        with connection:
            connection.executescript(script)
            connection.execute(
                "INSERT INTO schema_migrations (id, applied_at) VALUES (?, ?)",
                (path.name, now_iso()),
            )
        applied_ids.append(path.name)
    return applied_ids
