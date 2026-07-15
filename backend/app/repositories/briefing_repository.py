from __future__ import annotations

import sqlite3
from typing import Any

from backend.app.core.clock import now_iso
from backend.app.services.ids import make_id

_PATCH_COLUMNS = {
    "preparedBy": "prepared_by",
    "situationSummary": "situation_summary",
    "actionNote": "action_note",
    "summaryMode": "summary_mode",
    "status": "status",
    "aiModel": "ai_model",
    "aiPromptVersion": "ai_prompt_version",
    "aiGeneratedAt": "ai_generated_at",
    "aiInputSignature": "ai_input_signature",
}


class BriefingNotFound(Exception):
    pass


class RevisionConflict(Exception):
    pass


class BriefingFinalized(Exception):
    pass


def get_by_date(connection: sqlite3.Connection, report_date: str) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT * FROM briefings WHERE report_date = ?", (report_date,)
    ).fetchone()


def get_by_id(connection: sqlite3.Connection, briefing_id: str) -> sqlite3.Row | None:
    return connection.execute("SELECT * FROM briefings WHERE id = ?", (briefing_id,)).fetchone()


def create_or_update(
    connection: sqlite3.Connection,
    report_date: str,
    expected_revision: int,
    patch: dict[str, Any],
) -> sqlite3.Row:
    existing = get_by_date(connection, report_date)
    now = now_iso()
    columns = {_PATCH_COLUMNS[key]: value for key, value in patch.items() if key in _PATCH_COLUMNS}

    if existing is None:
        if expected_revision != 0:
            raise RevisionConflict()
        briefing_id = make_id()
        connection.execute(
            """
            INSERT INTO briefings (
                id, report_date, prepared_by, status, situation_summary, action_note,
                summary_mode, ai_model, ai_prompt_version, ai_generated_at, ai_input_signature,
                revision, latest_final_version, finalized_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, NULL, NULL, ?, ?)
            """,
            (
                briefing_id,
                report_date,
                columns.get("prepared_by"),
                columns.get("status", "draft"),
                columns.get("situation_summary"),
                columns.get("action_note"),
                columns.get("summary_mode"),
                columns.get("ai_model"),
                columns.get("ai_prompt_version"),
                columns.get("ai_generated_at"),
                columns.get("ai_input_signature"),
                now,
                now,
            ),
        )
        return get_by_id(connection, briefing_id)

    if existing["status"] == "final":
        raise BriefingFinalized()
    if existing["revision"] != expected_revision:
        raise RevisionConflict()
    if not columns:
        return existing

    assignments = ", ".join(f"{column} = ?" for column in columns)
    values = [*columns.values(), now, report_date, expected_revision]
    cursor = connection.execute(
        f"""
        UPDATE briefings
        SET {assignments}, revision = revision + 1, updated_at = ?
        WHERE report_date = ? AND revision = ?
        RETURNING *
        """,
        values,
    )
    row = cursor.fetchone()
    if row is None:
        raise RevisionConflict()
    return row


def _ensure_briefing_article_row(connection: sqlite3.Connection, briefing_id: str, article_id: str) -> None:
    now = now_iso()
    connection.execute(
        """
        INSERT INTO briefing_articles (
            briefing_id, article_id, selected, starred, note, dismissed, sort_order,
            created_at, updated_at
        )
        SELECT ?, ?, 0, 0, NULL, 0,
               COALESCE((SELECT MAX(sort_order) + 1 FROM briefing_articles WHERE briefing_id = ?), 0),
               ?, ?
        WHERE NOT EXISTS (
            SELECT 1 FROM briefing_articles WHERE briefing_id = ? AND article_id = ?
        )
        """,
        (briefing_id, article_id, briefing_id, now, now, briefing_id, article_id),
    )


def _bump_revision(connection: sqlite3.Connection, briefing_id: str, expected_revision: int) -> sqlite3.Row:
    cursor = connection.execute(
        """
        UPDATE briefings SET revision = revision + 1, updated_at = ?
        WHERE id = ? AND revision = ?
        RETURNING *
        """,
        (now_iso(), briefing_id, expected_revision),
    )
    row = cursor.fetchone()
    if row is None:
        raise RevisionConflict()
    return row


_ARTICLE_STATE_COLUMNS = {"selected", "starred", "note", "dismissed", "sortOrder"}
_ARTICLE_STATE_DB_COLUMN = {"selected": "selected", "starred": "starred", "note": "note", "dismissed": "dismissed", "sortOrder": "sort_order"}


def patch_article_state(
    connection: sqlite3.Connection,
    report_date: str,
    article_id: str,
    expected_revision: int,
    fields: dict[str, Any],
) -> sqlite3.Row:
    briefing = get_by_date(connection, report_date)
    if briefing is None:
        raise BriefingNotFound()
    if briefing["status"] == "final":
        raise BriefingFinalized()
    if briefing["revision"] != expected_revision:
        raise RevisionConflict()

    _ensure_briefing_article_row(connection, briefing["id"], article_id)

    patch = {key: value for key, value in fields.items() if key in _ARTICLE_STATE_COLUMNS}
    if patch.get("dismissed") is True:
        patch["selected"] = False

    if patch:
        assignments = ", ".join(f"{_ARTICLE_STATE_DB_COLUMN[key]} = ?" for key in patch)
        values = [
            (1 if value is True else 0 if value is False else value) for value in patch.values()
        ]
        connection.execute(
            f"""
            UPDATE briefing_articles SET {assignments}, updated_at = ?
            WHERE briefing_id = ? AND article_id = ?
            """,
            [*values, now_iso(), briefing["id"], article_id],
        )

    return _bump_revision(connection, briefing["id"], expected_revision)


def mark_selected(connection: sqlite3.Connection, briefing_id: str, article_id: str) -> None:
    """수동 기사 추가 직후 기본값(선정=true, 숨김 해제)을 부여한다. revision 검증은 하지 않는다."""
    _ensure_briefing_article_row(connection, briefing_id, article_id)
    connection.execute(
        "UPDATE briefing_articles SET selected = 1, dismissed = 0, updated_at = ? WHERE briefing_id = ? AND article_id = ?",
        (now_iso(), briefing_id, article_id),
    )


def set_article_state(
    connection: sqlite3.Connection,
    briefing_id: str,
    article_id: str,
    *,
    selected: bool,
    starred: bool,
    note: str | None,
    dismissed: bool,
    sort_order: int,
) -> None:
    """JSON/CSV import 등 대량 반영 시 revision 검증 없이 상태를 직접 설정한다."""
    _ensure_briefing_article_row(connection, briefing_id, article_id)
    connection.execute(
        """
        UPDATE briefing_articles
        SET selected = ?, starred = ?, note = ?, dismissed = ?, sort_order = ?, updated_at = ?
        WHERE briefing_id = ? AND article_id = ?
        """,
        (
            1 if selected else 0,
            1 if starred else 0,
            note,
            1 if dismissed else 0,
            sort_order,
            now_iso(),
            briefing_id,
            article_id,
        ),
    )


def reorder_articles(
    connection: sqlite3.Connection,
    report_date: str,
    expected_revision: int,
    article_ids: list[str],
) -> sqlite3.Row:
    briefing = get_by_date(connection, report_date)
    if briefing is None:
        raise BriefingNotFound()
    if briefing["status"] == "final":
        raise BriefingFinalized()
    if briefing["revision"] != expected_revision:
        raise RevisionConflict()

    now = now_iso()
    for index, article_id in enumerate(article_ids):
        _ensure_briefing_article_row(connection, briefing["id"], article_id)
        connection.execute(
            "UPDATE briefing_articles SET sort_order = ?, updated_at = ? WHERE briefing_id = ? AND article_id = ?",
            (index, now, briefing["id"], article_id),
        )

    return _bump_revision(connection, briefing["id"], expected_revision)
