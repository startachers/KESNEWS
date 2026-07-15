from __future__ import annotations

import sqlite3

from backend.app.repositories.article_repository import list_candidate_article_ids
from backend.app.services.ids import make_id


def create_run(
    connection: sqlite3.Connection,
    *,
    report_date: str,
    started_at: str,
    lookback_hours: int,
) -> str:
    run_id = make_id()
    connection.execute(
        """
        INSERT INTO collection_runs (
            id, report_date, started_at, finished_at, status, lookback_hours,
            raw_count, accepted_count, unique_count, stale_reused_count,
            warning_count, error_count
        ) VALUES (?, ?, ?, NULL, 'running', ?, 0, 0, 0, 0, 0, 0)
        """,
        (run_id, report_date, started_at, lookback_hours),
    )
    return run_id


def finish_run(
    connection: sqlite3.Connection,
    run_id: str,
    *,
    status: str,
    finished_at: str,
    raw_count: int,
    accepted_count: int,
    unique_count: int,
    stale_reused_count: int,
    warning_count: int,
    error_count: int,
) -> None:
    connection.execute(
        """
        UPDATE collection_runs
        SET status = ?, finished_at = ?, raw_count = ?, accepted_count = ?, unique_count = ?,
            stale_reused_count = ?, warning_count = ?, error_count = ?
        WHERE id = ?
        """,
        (status, finished_at, raw_count, accepted_count, unique_count, stale_reused_count, warning_count, error_count, run_id),
    )


def add_provider_result(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    provider: str,
    query_group_id: str | None,
    status: str,
    started_at: str | None,
    finished_at: str | None,
    raw_count: int,
    accepted_count: int,
    duplicate_count: int,
    warning_message: str | None,
    error_code: str | None,
    error_message: str | None,
) -> str:
    provider_id = make_id()
    connection.execute(
        """
        INSERT INTO collection_run_providers (
            id, collection_run_id, provider, query_group_id, status, started_at, finished_at,
            raw_count, accepted_count, duplicate_count, stale_reused_count,
            warning_message, error_code, error_message
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
        """,
        (
            provider_id,
            run_id,
            provider,
            query_group_id,
            status,
            started_at,
            finished_at,
            raw_count,
            accepted_count,
            duplicate_count,
            warning_message,
            error_code,
            error_message,
        ),
    )
    return provider_id


def get_latest_run(connection: sqlite3.Connection, report_date: str) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT * FROM collection_runs WHERE report_date = ? ORDER BY started_at DESC LIMIT 1",
        (report_date,),
    ).fetchone()


def get_latest_run_any_date(connection: sqlite3.Connection) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT * FROM collection_runs ORDER BY started_at DESC LIMIT 1"
    ).fetchone()


def get_latest_successful_run(connection: sqlite3.Connection) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT * FROM collection_runs WHERE status IN ('success', 'partial') "
        "ORDER BY finished_at DESC LIMIT 1"
    ).fetchone()


def serialize_status(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return {
        "id": row["id"],
        "reportDate": row["report_date"],
        "status": row["status"],
        "startedAt": row["started_at"],
        "finishedAt": row["finished_at"],
        "warningCount": row["warning_count"],
        "errorCount": row["error_count"],
    }


def get_run(connection: sqlite3.Connection, run_id: str) -> sqlite3.Row | None:
    return connection.execute("SELECT * FROM collection_runs WHERE id = ?", (run_id,)).fetchone()


def list_providers(connection: sqlite3.Connection, run_id: str) -> list[sqlite3.Row]:
    return connection.execute(
        "SELECT * FROM collection_run_providers WHERE collection_run_id = ?", (run_id,)
    ).fetchall()


def failed_providers(connection: sqlite3.Connection, run_id: str) -> list[str]:
    rows = connection.execute(
        "SELECT provider FROM collection_run_providers WHERE collection_run_id = ? AND status = 'failed'",
        (run_id,),
    ).fetchall()
    return [row["provider"] for row in rows]


def unrefreshed_candidate_ids(connection: sqlite3.Connection, report_date: str, run_id: str) -> set[str]:
    """LEG-001: 이번 run이 관측하지 못한(=실패 provider에 속했을 수 있는) 기존 후보 기사 id."""
    candidate_ids = list_candidate_article_ids(connection, report_date)
    if not candidate_ids:
        return set()
    placeholders = ",".join("?" for _ in candidate_ids)
    rows = connection.execute(
        f"""
        SELECT a.id AS id FROM articles a
        WHERE a.id IN ({placeholders}) AND NOT EXISTS (
            SELECT 1 FROM article_observations ao
            JOIN collection_run_providers crp ON crp.id = ao.collection_run_provider_id
            WHERE ao.article_id = a.id AND crp.collection_run_id = ?
        )
        """,
        [*candidate_ids, run_id],
    ).fetchall()
    return {row["id"] for row in rows}


def get_last_successful_finished_at(connection: sqlite3.Connection, report_date: str) -> str | None:
    row = connection.execute(
        "SELECT finished_at FROM collection_runs WHERE report_date = ? AND status = 'success' "
        "ORDER BY finished_at DESC LIMIT 1",
        (report_date,),
    ).fetchone()
    return row["finished_at"] if row else None
