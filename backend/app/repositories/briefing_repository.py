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

MAX_TOP_ISSUES = 6


class BriefingNotFound(Exception):
    pass


class RevisionConflict(Exception):
    pass


class BriefingFinalized(Exception):
    pass


class TopIssueLimitExceeded(Exception):
    pass


class DailyWorkResetBlocked(Exception):
    pass


def _top_issue_count(connection: sqlite3.Connection, briefing_id: str) -> int:
    briefing = get_by_id(connection, briefing_id)
    if briefing is None:
        return 0
    units = {
        f"issue:{row['issue_id']}"
        for row in connection.execute(
            "SELECT issue_id FROM briefing_issues WHERE briefing_id = ? AND selected = 1",
            (briefing_id,),
        )
    }
    top_articles = connection.execute(
        "SELECT article_id FROM briefing_articles WHERE briefing_id = ? AND top_issue = 1",
        (briefing_id,),
    ).fetchall()
    for row in top_articles:
        issue_id = _effective_issue_id_for_article(
            connection, briefing["report_date"], row["article_id"]
        )
        units.add(f"issue:{issue_id}" if issue_id else f"article:{row['article_id']}")
    return len(units)


def get_by_date(connection: sqlite3.Connection, report_date: str) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT * FROM briefings WHERE report_date = ?", (report_date,)
    ).fetchone()


def get_by_id(connection: sqlite3.Connection, briefing_id: str) -> sqlite3.Row | None:
    return connection.execute("SELECT * FROM briefings WHERE id = ?", (briefing_id,)).fetchone()


def list_recent(connection: sqlite3.Connection, limit: int = 100) -> list[sqlite3.Row]:
    return connection.execute(
        "SELECT * FROM briefings ORDER BY report_date DESC LIMIT ?", (limit,)
    ).fetchall()


def reset_daily_work(
    connection: sqlite3.Connection, report_date: str, expected_revision: int
) -> tuple[sqlite3.Row, dict[str, int]]:
    """불변 최종본은 보존하고 해당 보고일의 현재 작업 데이터 연결을 모두 제거한다."""
    briefing = get_by_date(connection, report_date)
    if briefing is None:
        raise BriefingNotFound()
    if briefing["status"] == "final":
        raise BriefingFinalized()
    if briefing["revision"] != expected_revision:
        raise RevisionConflict()
    running_count = connection.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM collection_runs WHERE report_date = ? AND status = 'running')
          + (SELECT COUNT(*) FROM ai_runs WHERE briefing_id = ? AND status = 'running')
          + (SELECT COUNT(*) FROM ai_selection_runs WHERE briefing_id = ? AND status = 'running')
        """,
        (report_date, briefing["id"], briefing["id"]),
    ).fetchone()[0]
    if running_count:
        raise DailyWorkResetBlocked()

    counts = {
        "articles": connection.execute(
            "SELECT COUNT(*) FROM briefing_articles WHERE briefing_id = ?",
            (briefing["id"],),
        ).fetchone()[0],
        "issues": connection.execute(
            """
            SELECT COUNT(*) FROM issues
            WHERE last_cluster_run_id IN (
                SELECT id FROM cluster_runs WHERE report_date = ?
            )
            """,
            (report_date,),
        ).fetchone()[0],
        "collectionRuns": connection.execute(
            "SELECT COUNT(*) FROM collection_runs WHERE report_date = ?",
            (report_date,),
        ).fetchone()[0],
        "aiRuns": connection.execute(
            "SELECT COUNT(*) FROM ai_runs WHERE briefing_id = ?",
            (briefing["id"],),
        ).fetchone()[0],
        "selectionRuns": connection.execute(
            "SELECT COUNT(*) FROM ai_selection_runs WHERE briefing_id = ?",
            (briefing["id"],),
        ).fetchone()[0],
    }

    connection.execute(
        "DELETE FROM briefing_report_drafts WHERE briefing_id = ?", (briefing["id"],)
    )
    connection.execute(
        "DELETE FROM ai_selection_runs WHERE briefing_id = ?", (briefing["id"],)
    )
    connection.execute("DELETE FROM ai_runs WHERE briefing_id = ?", (briefing["id"],))
    connection.execute(
        "DELETE FROM issue_review_assessments WHERE briefing_id = ?", (briefing["id"],)
    )
    connection.execute(
        "DELETE FROM briefing_issues WHERE briefing_id = ?", (briefing["id"],)
    )
    # issue 원본과 membership은 여러 보고일의 검토 기록에서 재사용될 수 있다. 오늘 실행만
    # 비활성화하고 briefing별 Top/메모/검토 연결은 위에서 제거한다. 기사 후보 연결이 제거되므로
    # 오늘 화면에서는 이슈가 사라지고, 재수집 후 새 군집 실행이 다시 계산한다.
    connection.execute(
        "UPDATE cluster_runs SET status = 'reset', applied_at = NULL "
        "WHERE report_date = ? AND status != 'running'",
        (report_date,),
    )
    connection.execute(
        "DELETE FROM briefing_articles WHERE briefing_id = ?", (briefing["id"],)
    )
    connection.execute(
        """
        DELETE FROM article_observations
        WHERE collection_run_provider_id IN (
            SELECT crp.id
            FROM collection_run_providers crp
            JOIN collection_runs cr ON cr.id = crp.collection_run_id
            WHERE cr.report_date = ?
        )
        """,
        (report_date,),
    )
    connection.execute(
        """
        DELETE FROM collection_run_providers
        WHERE collection_run_id IN (
            SELECT id FROM collection_runs WHERE report_date = ?
        )
        """,
        (report_date,),
    )
    connection.execute("DELETE FROM collection_runs WHERE report_date = ?", (report_date,))
    row = connection.execute(
        """
        UPDATE briefings
        SET prepared_by = NULL,
            status = 'draft',
            situation_summary = NULL,
            action_note = NULL,
            summary_mode = NULL,
            ai_model = NULL,
            ai_prompt_version = NULL,
            ai_generated_at = NULL,
            ai_input_signature = NULL,
            finalized_at = NULL,
            revision = revision + 1,
            updated_at = ?
        WHERE id = ? AND revision = ?
        RETURNING *
        """,
        (now_iso(), briefing["id"], expected_revision),
    ).fetchone()
    if row is None:
        raise RevisionConflict()
    return row, counts


def create_or_update(
    connection: sqlite3.Connection,
    report_date: str,
    expected_revision: int,
    patch: dict[str, Any],
) -> sqlite3.Row:
    existing = get_by_date(connection, report_date)
    now = now_iso()
    columns = {_PATCH_COLUMNS[key]: value for key, value in patch.items() if key in _PATCH_COLUMNS}

    if columns.get("status") == "final":
        raise BriefingFinalized()

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


def finalize(
    connection: sqlite3.Connection,
    briefing_id: str,
    expected_revision: int,
    version: int,
    finalized_at: str,
) -> sqlite3.Row:
    briefing = get_by_id(connection, briefing_id)
    if briefing is None:
        raise BriefingNotFound()
    if briefing["status"] == "final":
        raise BriefingFinalized()
    if briefing["revision"] != expected_revision:
        raise RevisionConflict()
    cursor = connection.execute(
        """
        UPDATE briefings
        SET status = 'final', latest_final_version = ?, finalized_at = ?,
            revision = revision + 1, updated_at = ?
        WHERE id = ? AND revision = ? AND status != 'final'
        RETURNING *
        """,
        (version, finalized_at, finalized_at, briefing_id, expected_revision),
    )
    row = cursor.fetchone()
    if row is None:
        raise RevisionConflict()
    return row


def reopen(
    connection: sqlite3.Connection, report_date: str, expected_revision: int
) -> sqlite3.Row:
    briefing = get_by_date(connection, report_date)
    if briefing is None:
        raise BriefingNotFound()
    if briefing["revision"] != expected_revision:
        raise RevisionConflict()
    if briefing["status"] != "final":
        return briefing
    cursor = connection.execute(
        """
        UPDATE briefings
        SET status = 'draft', finalized_at = NULL,
            revision = revision + 1, updated_at = ?
        WHERE id = ? AND revision = ? AND status = 'final'
        RETURNING *
        """,
        (now_iso(), briefing["id"], expected_revision),
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


def _ensure_briefing_issue_row(
    connection: sqlite3.Connection, briefing_id: str, issue_id: str
) -> None:
    now = now_iso()
    connection.execute(
        """
        INSERT INTO briefing_issues (
            briefing_id, issue_id, selected, starred, note, sort_order, created_at, updated_at
        )
        SELECT ?, ?, 0, 0, NULL,
               COALESCE((SELECT MAX(sort_order) + 1 FROM briefing_issues WHERE briefing_id = ?), 0),
               ?, ?
        WHERE NOT EXISTS (
            SELECT 1 FROM briefing_issues WHERE briefing_id = ? AND issue_id = ?
        )
        """,
        (briefing_id, issue_id, briefing_id, now, now, briefing_id, issue_id),
    )


def _effective_issue_id_for_article(
    connection: sqlite3.Connection, report_date: str, article_id: str
) -> str | None:
    row = connection.execute(
        """
        SELECT i.id
        FROM issues i
        JOIN cluster_runs cr ON cr.id = i.last_cluster_run_id
        WHERE cr.report_date = ?
          AND (
              EXISTS (
                  SELECT 1 FROM issue_auto_articles iaa
                  WHERE iaa.issue_id = i.id
                    AND iaa.cluster_run_id = i.last_cluster_run_id
                    AND iaa.article_id = ?
              )
              OR EXISTS (
                  SELECT 1 FROM issue_membership_overrides added
                  WHERE added.issue_id = i.id
                    AND added.article_id = ?
                    AND added.action = 'add'
              )
          )
          AND NOT EXISTS (
              SELECT 1 FROM issue_membership_overrides removed
              WHERE removed.issue_id = i.id
                AND removed.article_id = ?
                AND removed.action = 'remove'
          )
        ORDER BY i.manual_group DESC, i.updated_at DESC, i.id
        LIMIT 1
        """,
        (report_date, article_id, article_id, article_id),
    ).fetchone()
    return row["id"] if row else None


def _effective_article_ids_for_issue(
    connection: sqlite3.Connection, issue_id: str
) -> list[str]:
    rows = connection.execute(
        """
        WITH automatic AS (
            SELECT iaa.article_id
            FROM issue_auto_articles iaa
            JOIN issues i ON i.id = iaa.issue_id
            WHERE iaa.issue_id = ? AND iaa.cluster_run_id = i.last_cluster_run_id
        ), added AS (
            SELECT article_id FROM issue_membership_overrides
            WHERE issue_id = ? AND action = 'add'
        ), removed AS (
            SELECT article_id FROM issue_membership_overrides
            WHERE issue_id = ? AND action = 'remove'
        )
        SELECT article_id FROM (SELECT article_id FROM automatic UNION SELECT article_id FROM added)
        WHERE article_id NOT IN (SELECT article_id FROM removed)
        """,
        (issue_id, issue_id, issue_id),
    ).fetchall()
    return [row["article_id"] for row in rows]


def bump_revision(connection: sqlite3.Connection, briefing_id: str, expected_revision: int) -> sqlite3.Row:
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


_ARTICLE_STATE_COLUMNS = {"selected", "starred", "topIssue", "note", "dismissed", "sortOrder"}
_ARTICLE_STATE_DB_COLUMN = {"selected": "selected", "starred": "starred", "topIssue": "top_issue", "note": "note", "dismissed": "dismissed", "sortOrder": "sort_order"}


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
    if patch.get("topIssue") is True:
        issue_id = _effective_issue_id_for_article(connection, report_date, article_id)
        if issue_id is not None:
            current_issue = connection.execute(
                "SELECT selected FROM briefing_issues WHERE briefing_id = ? AND issue_id = ?",
                (briefing["id"], issue_id),
            ).fetchone()
            if (
                (current_issue is None or not bool(current_issue["selected"]))
                and _top_issue_count(connection, briefing["id"]) >= MAX_TOP_ISSUES
            ):
                raise TopIssueLimitExceeded()
            _ensure_briefing_issue_row(connection, briefing["id"], issue_id)
            connection.execute(
                "UPDATE briefing_issues SET selected = 1, updated_at = ? "
                "WHERE briefing_id = ? AND issue_id = ?",
                (now_iso(), briefing["id"], issue_id),
            )
            patch["topIssue"] = False
        else:
            current = connection.execute(
                "SELECT top_issue FROM briefing_articles WHERE briefing_id = ? AND article_id = ?",
                (briefing["id"], article_id),
            ).fetchone()
            limit_reached = _top_issue_count(connection, briefing["id"]) >= MAX_TOP_ISSUES
            if current is not None and not bool(current["top_issue"]) and limit_reached:
                raise TopIssueLimitExceeded()
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

    return bump_revision(connection, briefing["id"], expected_revision)


def mark_selected(connection: sqlite3.Connection, briefing_id: str, article_id: str) -> None:
    """수동 기사 추가 직후 기본값(선정=true, 숨김 해제)을 부여한다. revision 검증은 하지 않는다."""
    _ensure_briefing_article_row(connection, briefing_id, article_id)
    connection.execute(
        "UPDATE briefing_articles SET selected = 1, dismissed = 0, updated_at = ? WHERE briefing_id = ? AND article_id = ?",
        (now_iso(), briefing_id, article_id),
    )


def apply_ai_recommendations(
    connection: sqlite3.Connection,
    report_date: str,
    expected_revision: int,
    article_ids: list[str],
    *,
    selection_limit: int = 12,
    top_issue_limit: int = MAX_TOP_ISSUES,
) -> tuple[sqlite3.Row, list[str], list[str], list[str], int]:
    """추천 기사를 추가하고 빈 Top 자리를 추천 군집 또는 단독 기사로 채운다."""
    briefing = get_by_date(connection, report_date)
    if briefing is None:
        raise BriefingNotFound()
    if briefing["status"] == "final":
        raise BriefingFinalized()
    if briefing["revision"] != expected_revision:
        raise RevisionConflict()

    selected_count = connection.execute(
        "SELECT COUNT(*) FROM briefing_articles WHERE briefing_id = ? AND selected = 1",
        (briefing["id"],),
    ).fetchone()[0]
    applied: list[str] = []
    for article_id in dict.fromkeys(article_ids):
        if selected_count >= selection_limit:
            break
        candidate = connection.execute(
            """
            SELECT a.id, COALESCE(ba.selected, 0) AS selected,
                   COALESCE(ba.dismissed, 0) AS dismissed
            FROM articles a
            LEFT JOIN briefing_articles ba
              ON ba.briefing_id = ? AND ba.article_id = a.id
            WHERE a.id = ?
            """,
            (briefing["id"], article_id),
        ).fetchone()
        if candidate is None or bool(candidate["dismissed"]) or bool(candidate["selected"]):
            continue
        _ensure_briefing_article_row(connection, briefing["id"], article_id)
        connection.execute(
            """
            UPDATE briefing_articles
            SET selected = 1, updated_at = ?
            WHERE briefing_id = ? AND article_id = ? AND dismissed = 0
            """,
            (now_iso(), briefing["id"], article_id),
        )
        applied.append(article_id)
        selected_count += 1

    available_top_slots = max(
        0,
        top_issue_limit - _top_issue_count(connection, briefing["id"]),
    )
    top_issue_issue_ids: list[str] = []
    top_issue_article_ids: list[str] = []
    for article_id in applied[:top_issue_limit]:
        if available_top_slots <= 0:
            break
        issue_id = _effective_issue_id_for_article(connection, report_date, article_id)
        if issue_id is not None:
            current = connection.execute(
                "SELECT selected FROM briefing_issues WHERE briefing_id = ? AND issue_id = ?",
                (briefing["id"], issue_id),
            ).fetchone()
            if current is not None and bool(current["selected"]):
                continue
            _ensure_briefing_issue_row(connection, briefing["id"], issue_id)
            connection.execute(
                "UPDATE briefing_issues SET selected = 1, updated_at = ? "
                "WHERE briefing_id = ? AND issue_id = ?",
                (now_iso(), briefing["id"], issue_id),
            )
            top_issue_issue_ids.append(issue_id)
        else:
            current = connection.execute(
                "SELECT top_issue FROM briefing_articles WHERE briefing_id = ? AND article_id = ?",
                (briefing["id"], article_id),
            ).fetchone()
            if current is not None and bool(current["top_issue"]):
                continue
            connection.execute(
                "UPDATE briefing_articles SET top_issue = 1, updated_at = ? "
                "WHERE briefing_id = ? AND article_id = ?",
                (now_iso(), briefing["id"], article_id),
            )
            top_issue_article_ids.append(article_id)
        available_top_slots -= 1

    return (
        bump_revision(connection, briefing["id"], expected_revision),
        applied,
        top_issue_issue_ids,
        top_issue_article_ids,
        _top_issue_count(connection, briefing["id"]),
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
    top_issue: bool = False,
) -> None:
    """JSON/CSV import 등 대량 반영 시 revision 검증 없이 상태를 직접 설정한다."""
    _ensure_briefing_article_row(connection, briefing_id, article_id)
    connection.execute(
        """
        UPDATE briefing_articles
        SET selected = ?, starred = ?, top_issue = ?, note = ?, dismissed = ?, sort_order = ?, updated_at = ?
        WHERE briefing_id = ? AND article_id = ?
        """,
        (
            1 if selected else 0,
            1 if starred else 0,
            1 if top_issue else 0,
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

    return bump_revision(connection, briefing["id"], expected_revision)


def patch_issue_state(
    connection: sqlite3.Connection,
    report_date: str,
    issue_id: str,
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
    now = now_iso()
    connection.execute(
        """
        INSERT INTO briefing_issues (
            briefing_id, issue_id, selected, starred, note, sort_order, created_at, updated_at
        )
        SELECT ?, ?, 0, 0, NULL,
               COALESCE((SELECT MAX(sort_order) + 1 FROM briefing_issues WHERE briefing_id = ?), 0),
               ?, ?
        WHERE NOT EXISTS (
            SELECT 1 FROM briefing_issues WHERE briefing_id = ? AND issue_id = ?
        )
        """,
        (briefing["id"], issue_id, briefing["id"], now, now, briefing["id"], issue_id),
    )
    column_map = {"selected": "selected", "starred": "starred", "note": "note", "sortOrder": "sort_order"}
    patch = {key: value for key, value in fields.items() if key in column_map}
    if patch.get("selected") is True:
        current = connection.execute(
            "SELECT selected FROM briefing_issues WHERE briefing_id = ? AND issue_id = ?",
            (briefing["id"], issue_id),
        ).fetchone()
        member_ids = _effective_article_ids_for_issue(connection, issue_id)
        member_top_exists = False
        if member_ids:
            placeholders = ",".join("?" for _ in member_ids)
            member_top_exists = connection.execute(
                f"SELECT 1 FROM briefing_articles "  # noqa: S608
                f"WHERE briefing_id = ? AND top_issue = 1 AND article_id IN ({placeholders}) LIMIT 1",
                (briefing["id"], *member_ids),
            ).fetchone() is not None
        limit_reached = _top_issue_count(connection, briefing["id"]) >= MAX_TOP_ISSUES
        if (
            current is not None
            and not bool(current["selected"])
            and not member_top_exists
            and limit_reached
        ):
            raise TopIssueLimitExceeded()
    if "selected" in patch:
        member_ids = _effective_article_ids_for_issue(connection, issue_id)
        if member_ids:
            placeholders = ",".join("?" for _ in member_ids)
            connection.execute(
                f"UPDATE briefing_articles SET top_issue = 0, updated_at = ? "  # noqa: S608
                f"WHERE briefing_id = ? AND article_id IN ({placeholders}) AND top_issue = 1",
                (now, briefing["id"], *member_ids),
            )
    if patch:
        assignments = ", ".join(f"{column_map[key]} = ?" for key in patch)
        values = [1 if value is True else 0 if value is False else value for value in patch.values()]
        connection.execute(
            f"UPDATE briefing_issues SET {assignments}, updated_at = ? "  # noqa: S608
            "WHERE briefing_id = ? AND issue_id = ?",
            (*values, now, briefing["id"], issue_id),
        )
    review_patch = {
        key: fields[key]
        for key in ("editorReviewStars", "editorReviewReason")
        if key in fields
    }
    if review_patch:
        connection.execute(
            """
            INSERT INTO issue_review_assessments (
                briefing_id, issue_id, editor_stars, editor_reason, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(briefing_id, issue_id) DO UPDATE SET
                editor_stars = CASE WHEN ? THEN excluded.editor_stars ELSE issue_review_assessments.editor_stars END,
                editor_reason = CASE WHEN ? THEN excluded.editor_reason ELSE issue_review_assessments.editor_reason END,
                updated_at = excluded.updated_at
            """,
            (
                briefing["id"], issue_id,
                review_patch.get("editorReviewStars"),
                review_patch.get("editorReviewReason"), now,
                1 if "editorReviewStars" in review_patch else 0,
                1 if "editorReviewReason" in review_patch else 0,
            ),
        )
    return bump_revision(connection, briefing["id"], expected_revision)


def list_issue_states(connection: sqlite3.Connection, report_date: str) -> dict[str, dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT bi.issue_id, bi.selected, bi.starred, bi.note, bi.sort_order
        FROM briefing_issues bi
        JOIN briefings b ON b.id = bi.briefing_id
        WHERE b.report_date = ?
        """,
        (report_date,),
    ).fetchall()
    return {
        row["issue_id"]: {
            "selected": bool(row["selected"]),
            "starred": bool(row["starred"]),
            "note": row["note"] or "",
            "sortOrder": row["sort_order"],
        }
        for row in rows
    }


def list_article_top_issue_ids(
    connection: sqlite3.Connection, report_date: str
) -> set[str]:
    rows = connection.execute(
        """
        SELECT ba.article_id
        FROM briefing_articles ba
        JOIN briefings b ON b.id = ba.briefing_id
        WHERE b.report_date = ? AND ba.top_issue = 1
        """,
        (report_date,),
    ).fetchall()
    return {row["article_id"] for row in rows}
