import sqlite3

from backend.app.db.migrator import apply_migrations, pending_migrations
from backend.app.repositories.database import get_connection

EXPECTED_TABLES = {
    "schema_migrations",
    "articles",
    "article_observations",
    "article_assessments",
    "briefings",
    "briefing_versions",
    "briefing_articles",
    "collection_runs",
    "collection_run_providers",
    "settings",
}


def _table_names(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {row[0] for row in rows}


def test_apply_migrations_creates_expected_tables(tmp_path):
    db_path = tmp_path / "test.db"
    connection = get_connection(db_path)
    try:
        applied = apply_migrations(connection)
        assert applied == ["0001_initial.sql"]
        assert EXPECTED_TABLES.issubset(_table_names(connection))
        assert pending_migrations(connection) == []
    finally:
        connection.close()


def test_apply_migrations_is_idempotent(tmp_path):
    db_path = tmp_path / "test.db"
    connection = get_connection(db_path)
    try:
        first = apply_migrations(connection)
        second = apply_migrations(connection)
        assert first == ["0001_initial.sql"]
        assert second == []
        assert EXPECTED_TABLES.issubset(_table_names(connection))
    finally:
        connection.close()


def test_foreign_key_constraints_are_enforced(tmp_path):
    db_path = tmp_path / "test.db"
    connection = get_connection(db_path)
    try:
        apply_migrations(connection)
        result = connection.execute("PRAGMA foreign_keys").fetchone()[0]
        assert result == 1
        try:
            connection.execute(
                "INSERT INTO briefing_articles (briefing_id, article_id, created_at, updated_at) "
                "VALUES ('missing-briefing', 'missing-article', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"
            )
            connection.commit()
            raised = False
        except sqlite3.IntegrityError:
            raised = True
        assert raised
    finally:
        connection.close()
