from __future__ import annotations

import json
import sqlite3
from typing import Any, Literal

from backend.app.core.clock import now_iso
from backend.app.repositories.article_repository import list_candidate_article_ids
from backend.app.services.ids import make_id


def clustering_input(connection: sqlite3.Connection, report_date: str) -> list[dict[str, Any]]:
    article_ids = sorted(list_candidate_article_ids(connection, report_date))
    if not article_ids:
        return []
    placeholders = ",".join("?" for _ in article_ids)
    rows = connection.execute(
        f"""
        SELECT a.id, a.title, a.description, a.source, a.published_at,
               aa.auto_relevance_score, aa.auto_severity_score, aa.auto_reasons_json
        FROM articles a
        LEFT JOIN article_assessments aa ON aa.article_id = a.id
        WHERE a.id IN ({placeholders})
        ORDER BY a.published_at, a.id
        """,  # noqa: S608 - placeholders count only
        article_ids,
    ).fetchall()
    result = []
    for row in rows:
        reasons = json.loads(row["auto_reasons_json"] or "{}")
        result.append(
            {
                "id": row["id"],
                "title": row["title"],
                "description": row["description"] or "",
                "source": row["source"] or "",
                "publishedAt": row["published_at"],
                "relevanceScore": row["auto_relevance_score"] or 0,
                "severityScore": row["auto_severity_score"] or 0,
                "directMention": bool(reasons.get("directMention")),
            }
        )
    return result


def _effective_article_ids(connection: sqlite3.Connection, issue_id: str) -> list[str]:
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
        ORDER BY article_id
        """,
        (issue_id, issue_id, issue_id),
    ).fetchall()
    return [row["article_id"] for row in rows]


def matching_state(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute("SELECT * FROM issues ORDER BY created_at, id").fetchall()
    result = []
    for row in rows:
        override = connection.execute(
            "SELECT 1 FROM issue_membership_overrides WHERE issue_id = ? LIMIT 1", (row["id"],)
        ).fetchone()
        result.append(
            {
                "id": row["id"],
                "effectiveArticleIds": _effective_article_ids(connection, row["id"]),
                "hasEditorOverride": bool(
                    row["editor_title"] or row["editor_status"] or row["editor_priority"] or override
                ),
            }
        )
    return result


def apply_proposal(
    connection: sqlite3.Connection, run_id: str, proposal: list[dict[str, Any]]
) -> list[str]:
    now = now_iso()
    matched_ids: list[str] = []
    for cluster in proposal:
        issue_id = cluster.get("existingIssueId") or make_id()
        matched_ids.append(issue_id)
        connection.execute(
            """
            INSERT INTO issues (
                id, representative_article_id, auto_title, auto_status, auto_priority,
                auto_priority_score, spread_score, auto_reasons_json, first_seen_at,
                last_seen_at, direct_mention, needs_review, last_cluster_run_id,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                representative_article_id = excluded.representative_article_id,
                auto_title = excluded.auto_title,
                auto_status = excluded.auto_status,
                auto_priority = excluded.auto_priority,
                auto_priority_score = excluded.auto_priority_score,
                spread_score = excluded.spread_score,
                auto_reasons_json = excluded.auto_reasons_json,
                first_seen_at = COALESCE(issues.first_seen_at, excluded.first_seen_at),
                last_seen_at = excluded.last_seen_at,
                direct_mention = excluded.direct_mention,
                needs_review = 0,
                last_cluster_run_id = excluded.last_cluster_run_id,
                updated_at = excluded.updated_at
            """,
            (
                issue_id,
                cluster["representativeArticleId"],
                cluster["autoTitle"],
                cluster["autoStatus"],
                cluster["autoPriority"],
                cluster["autoPriorityScore"],
                cluster["spreadScore"],
                json.dumps(cluster["autoReasons"], ensure_ascii=False),
                cluster["firstSeenAt"],
                cluster["lastSeenAt"],
                1 if cluster["directMention"] else 0,
                run_id,
                now,
                now,
            ),
        )
        for article_id in cluster["articleIds"]:
            connection.execute(
                """
                INSERT INTO issue_auto_articles (
                    issue_id, article_id, cluster_run_id, similarity_score, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    issue_id,
                    article_id,
                    run_id,
                    cluster.get("membershipScores", {}).get(article_id),
                    now,
                ),
            )

    existing_rows = connection.execute("SELECT id, editor_title, editor_status, editor_priority FROM issues").fetchall()
    for row in existing_rows:
        if row["id"] in matched_ids:
            continue
        has_membership_override = connection.execute(
            "SELECT 1 FROM issue_membership_overrides WHERE issue_id = ? LIMIT 1", (row["id"],)
        ).fetchone()
        needs_review = bool(
            row["editor_title"] or row["editor_status"] or row["editor_priority"] or has_membership_override
        )
        connection.execute(
            "UPDATE issues SET last_cluster_run_id = ?, needs_review = ?, updated_at = ? WHERE id = ?",
            (run_id, 1 if needs_review else 0, now, row["id"]),
        )
    return matched_ids


def _serialize_issue(connection: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    effective_ids = _effective_article_ids(connection, row["id"])
    automatic = connection.execute(
        """
        SELECT iaa.article_id FROM issue_auto_articles iaa
        JOIN issues i ON i.id = iaa.issue_id
        WHERE iaa.issue_id = ? AND iaa.cluster_run_id = i.last_cluster_run_id
        ORDER BY iaa.article_id
        """,
        (row["id"],),
    ).fetchall()
    memberships = connection.execute(
        "SELECT article_id, action FROM issue_membership_overrides WHERE issue_id = ? ORDER BY article_id",
        (row["id"],),
    ).fetchall()
    return {
        "id": row["id"],
        "representativeArticleId": row["representative_article_id"],
        "autoTitle": row["auto_title"],
        "editorTitle": row["editor_title"],
        "effectiveTitle": row["editor_title"] or row["auto_title"],
        "autoStatus": row["auto_status"],
        "editorStatus": row["editor_status"],
        "effectiveStatus": row["editor_status"] or row["auto_status"],
        "autoPriority": row["auto_priority"],
        "editorPriority": row["editor_priority"],
        "effectivePriority": row["editor_priority"] or row["auto_priority"],
        "autoPriorityScore": row["auto_priority_score"],
        "spreadScore": row["spread_score"],
        "autoReasons": json.loads(row["auto_reasons_json"] or "{}"),
        "firstSeenAt": row["first_seen_at"],
        "lastSeenAt": row["last_seen_at"],
        "directMention": bool(row["direct_mention"]),
        "needsReview": bool(row["needs_review"]),
        "articleIds": effective_ids,
        "autoArticleIds": [item["article_id"] for item in automatic],
        "membershipOverrides": [dict(item) for item in memberships],
        "lastClusterRunId": row["last_cluster_run_id"],
    }


def list_for_report_date(connection: sqlite3.Connection, report_date: str) -> list[dict[str, Any]]:
    candidate_ids = list_candidate_article_ids(connection, report_date)
    rows = connection.execute("SELECT * FROM issues ORDER BY last_seen_at DESC, id").fetchall()
    result = []
    for row in rows:
        serialized = _serialize_issue(connection, row)
        if candidate_ids.intersection(serialized["articleIds"]):
            result.append(serialized)
    return result


def get(connection: sqlite3.Connection, issue_id: str) -> sqlite3.Row | None:
    return connection.execute("SELECT * FROM issues WHERE id = ?", (issue_id,)).fetchone()


def patch_editor(
    connection: sqlite3.Connection,
    issue_id: str,
    patch: dict[str, str | None],
) -> sqlite3.Row:
    column_map = {
        "editorTitle": "editor_title",
        "editorStatus": "editor_status",
        "editorPriority": "editor_priority",
    }
    if patch:
        assignments = ", ".join(f"{column_map[key]} = ?" for key in patch)
        connection.execute(
            f"UPDATE issues SET {assignments}, updated_at = ? WHERE id = ?",  # noqa: S608
            (*patch.values(), now_iso(), issue_id),
        )
    return get(connection, issue_id)


def set_membership_override(
    connection: sqlite3.Connection,
    issue_id: str,
    article_id: str,
    action: Literal["add", "remove"],
) -> None:
    now = now_iso()
    connection.execute(
        """
        INSERT INTO issue_membership_overrides (issue_id, article_id, action, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(issue_id, article_id) DO UPDATE SET action = excluded.action, updated_at = excluded.updated_at
        """,
        (issue_id, article_id, action, now, now),
    )


def serialize_one(connection: sqlite3.Connection, issue_id: str) -> dict[str, Any] | None:
    row = get(connection, issue_id)
    return _serialize_issue(connection, row) if row else None


def import_snapshots(
    connection: sqlite3.Connection,
    report_date: str,
    snapshots: list[dict[str, Any]],
    article_id_map: dict[str, str],
) -> int:
    if not snapshots:
        return 0
    run_id = make_id()
    now = now_iso()
    connection.execute(
        """
        INSERT INTO cluster_runs (
            id, report_date, status, input_signature, proposal_json, diff_json,
            algorithm_version, created_at, applied_at
        ) VALUES (?, ?, 'applied', 'json-import', '[]', '{}', 'json-import-v1', ?, ?)
        """,
        (run_id, report_date, now, now),
    )
    imported = 0
    for snapshot in snapshots:
        auto_ids = [
            article_id_map[article_id]
            for article_id in snapshot.get("autoArticleIds", snapshot.get("articleIds", []))
            if article_id in article_id_map
        ]
        override_items = [
            item for item in snapshot.get("membershipOverrides", [])
            if item.get("article_id") in article_id_map
        ]
        if not auto_ids and not override_items:
            continue
        issue_id = make_id()
        representative_id = article_id_map.get(snapshot.get("representativeArticleId"))
        if representative_id is None and auto_ids:
            representative_id = auto_ids[0]
        connection.execute(
            """
            INSERT INTO issues (
                id, representative_article_id, auto_title, editor_title, auto_status,
                editor_status, auto_priority, editor_priority, auto_priority_score,
                spread_score, auto_reasons_json, first_seen_at, last_seen_at,
                direct_mention, needs_review, last_cluster_run_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                issue_id, representative_id, snapshot.get("autoTitle"), snapshot.get("editorTitle"),
                snapshot.get("autoStatus"), snapshot.get("editorStatus"), snapshot.get("autoPriority"),
                snapshot.get("editorPriority"), snapshot.get("autoPriorityScore"),
                snapshot.get("spreadScore", 0),
                json.dumps(snapshot.get("autoReasons") or {}, ensure_ascii=False),
                snapshot.get("firstSeenAt"), snapshot.get("lastSeenAt"),
                1 if snapshot.get("directMention") else 0, 1 if snapshot.get("needsReview") else 0,
                run_id, now, now,
            ),
        )
        for article_id in auto_ids:
            connection.execute(
                """
                INSERT INTO issue_auto_articles (
                    issue_id, article_id, cluster_run_id, similarity_score, created_at
                ) VALUES (?, ?, ?, NULL, ?)
                """,
                (issue_id, article_id, run_id, now),
            )
        for item in override_items:
            set_membership_override(
                connection,
                issue_id,
                article_id_map[item["article_id"]],
                item["action"],
            )
        imported += 1
    return imported
