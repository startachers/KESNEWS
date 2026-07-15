from __future__ import annotations

import sqlite3

"""Phase 8(CEO 보고 분리)의 finalize/reopen이 쓸 최소 조회 함수만 둔다.
snapshot 생성·apply 로직은 이번 Phase 범위가 아니다."""


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
