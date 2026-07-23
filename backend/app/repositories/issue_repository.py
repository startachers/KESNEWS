from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Literal

from backend.app.core.clock import now_iso
from backend.app.repositories.article_repository import list_candidate_article_ids
from backend.app.services.ids import make_id
from backend.app.services.review_priority import rank_issues
from backend.app.services.extraction.evidence_quality import latest_for_article, quality_for_article


def clustering_input(connection: sqlite3.Connection, report_date: str) -> list[dict[str, Any]]:
    article_ids = sorted(list_candidate_article_ids(connection, report_date))
    if not article_ids:
        return []
    placeholders = ",".join("?" for _ in article_ids)
    rows = connection.execute(
        f"""
        SELECT a.id, a.title, a.description, a.source, a.published_at,
               aa.auto_relevance_score, aa.auto_severity_score, aa.auto_reasons_json,
               COALESCE(aa.final_event_type, aa.auto_event_type) AS event_type,
               EXISTS (
                   SELECT 1
                   FROM article_observations government_observation
                   WHERE government_observation.article_id = a.id
                     AND government_observation.provider IN (
                         '국무조정실 보도자료',
                         '기후에너지환경부 보도자료',
                         '정책브리핑 API'
                     )
               ) AS is_government_press_release,
               COALESCE(aoa.final_origin_type, aoa.auto_origin_type) AS origin_type,
               CASE
                   WHEN aoa.final_origin_type = 'independent' THEN NULL
                   ELSE COALESCE(aoa.final_press_release_id, aoa.auto_press_release_id)
               END AS press_release_id,
               kpr.title AS press_release_title
        FROM articles a
        LEFT JOIN article_assessments aa ON aa.article_id = a.id
        LEFT JOIN article_origin_assessments aoa ON aoa.article_id = a.id
        LEFT JOIN kesco_press_releases kpr ON kpr.id = COALESCE(
            aoa.final_press_release_id, aoa.auto_press_release_id
        )
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
                "eventType": row["event_type"] or "general",
                "directMention": bool(reasons.get("directMention")),
                "governmentPressRelease": bool(row["is_government_press_release"]),
                "originType": row["origin_type"],
                "pressReleaseId": row["press_release_id"],
                "pressReleaseTitle": row["press_release_title"],
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
        if row["manual_group"]:
            continue
        override = connection.execute(
            "SELECT 1 FROM issue_membership_overrides WHERE issue_id = ? LIMIT 1", (row["id"],)
        ).fetchone()
        result.append(
            {
                "id": row["id"],
                "effectiveArticleIds": _effective_article_ids(connection, row["id"]),
                "hasEditorOverride": bool(
                    row["editor_title"] or row["editor_status"] or row["editor_priority"]
                    or row["manual_representative_article_id"]
                    or _json_ids(row["manual_supplemental_article_ids_json"])
                    or _json_ids(row["manual_excluded_article_ids_json"])
                    or override
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
        automatic_representative = _select_auto_representative(
            connection,
            cluster["articleIds"],
            excluded_ids=_json_ids(
                get(connection, issue_id)["manual_excluded_article_ids_json"]
            ),
            fallback_id=cluster["representativeArticleId"],
        )
        connection.execute(
            "UPDATE issues SET representative_article_id = ? WHERE id = ?",
            (automatic_representative, issue_id),
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
    report_date_row = connection.execute(
        "SELECT report_date FROM cluster_runs WHERE id = ?", (run_id,)
    ).fetchone()
    if report_date_row:
        _enforce_manual_group_exclusivity(connection, report_date_row["report_date"])
    return matched_ids


def apply_review_assessments(
    connection: sqlite3.Connection,
    report_date: str,
    proposal: list[dict[str, Any]],
    issue_ids: list[str],
) -> None:
    briefing = connection.execute(
        "SELECT id FROM briefings WHERE report_date = ?", (report_date,)
    ).fetchone()
    if briefing is None:
        return
    now = now_iso()
    for item, issue_id in zip(proposal, issue_ids, strict=True):
        connection.execute(
            """
            INSERT INTO issue_review_assessments (
                briefing_id, issue_id, auto_score, auto_rank, auto_stars,
                reasons_json, scoring_version, calculated_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(briefing_id, issue_id) DO UPDATE SET
                auto_score = excluded.auto_score,
                auto_rank = excluded.auto_rank,
                auto_stars = excluded.auto_stars,
                reasons_json = excluded.reasons_json,
                scoring_version = excluded.scoring_version,
                calculated_at = excluded.calculated_at,
                updated_at = excluded.updated_at
            """,
            (
                briefing["id"], issue_id, item.get("autoReviewScore"),
                item.get("autoReviewRank"), item.get("autoReviewStars"),
                json.dumps(item.get("reviewReasons") or {}, ensure_ascii=False),
                "review-v1", now, now,
            ),
        )


def recalculate_review_assessments(connection: sqlite3.Connection, report_date: str) -> None:
    items = list_for_report_date(connection, report_date)
    review_inputs: list[dict[str, Any]] = []
    for item in items:
        article_ids = item.get("articleIds") or []
        if not article_ids:
            continue
        placeholders = ",".join("?" for _ in article_ids)
        rows = connection.execute(
            f"""
            SELECT a.id, a.source, aa.auto_relevance_score, aa.auto_severity_score,
                   COALESCE(aa.final_event_type, aa.auto_event_type) AS event_type
            FROM articles a
            LEFT JOIN article_assessments aa ON aa.article_id = a.id
            WHERE a.id IN ({placeholders})
            """,  # noqa: S608 - placeholders count only
            article_ids,
        ).fetchall()
        review_inputs.append({
            "id": item["id"],
            "autoTitle": item.get("autoTitle"),
            "autoStatus": item.get("autoStatus"),
            "lastSeenAt": item.get("lastSeenAt"),
            "directMention": item.get("directMention"),
            "members": [
                {
                    "id": row["id"], "source": row["source"],
                    "relevanceScore": row["auto_relevance_score"] or 0,
                    "severityScore": row["auto_severity_score"] or 0,
                    "eventType": row["event_type"] or "general",
                }
                for row in rows
            ],
        })
    ranked = rank_issues(review_inputs, datetime.now(timezone.utc))
    apply_review_assessments(
        connection, report_date, ranked, [item["id"] for item in ranked]
    )


def report_date_for_issue(connection: sqlite3.Connection, issue_id: str) -> str | None:
    row = connection.execute(
        """
        SELECT cr.report_date FROM issues i
        JOIN cluster_runs cr ON cr.id = i.last_cluster_run_id
        WHERE i.id = ?
        """,
        (issue_id,),
    ).fetchone()
    return row["report_date"] if row else None


def _serialize_issue(connection: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    effective_ids = _effective_article_ids(connection, row["id"])
    excluded_ids = _json_ids(row["manual_excluded_article_ids_json"])
    supplemental_ids = _json_ids(row["manual_supplemental_article_ids_json"])
    manual_representative_id = row["manual_representative_article_id"]
    manual_representative_missing = bool(
        manual_representative_id and manual_representative_id not in effective_ids
    )
    effective_representative_id = (
        manual_representative_id
        if manual_representative_id in effective_ids and manual_representative_id not in excluded_ids
        else row["representative_article_id"]
        if row["representative_article_id"] in effective_ids and row["representative_article_id"] not in excluded_ids
        else None
    )
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
        "representativeArticleId": effective_representative_id,
        "autoRepresentativeArticleId": row["representative_article_id"],
        "manualRepresentativeArticleId": manual_representative_id,
        "manualRepresentative": bool(manual_representative_id and not manual_representative_missing),
        "manualRepresentativeMissing": manual_representative_missing,
        "manualSupplementalArticleIds": supplemental_ids,
        "manualExcludedArticleIds": excluded_ids,
        "manualSelectionUpdatedAt": row["manual_selection_updated_at"],
        "evidenceRevision": row["evidence_revision"],
        "representativeEvidenceMissing": effective_representative_id is None,
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
        "manualGroup": bool(row["manual_group"]),
        "articleIds": effective_ids,
        "autoArticleIds": [item["article_id"] for item in automatic],
        "membershipOverrides": [dict(item) for item in memberships],
        "lastClusterRunId": row["last_cluster_run_id"],
    }


def list_for_report_date(connection: sqlite3.Connection, report_date: str) -> list[dict[str, Any]]:
    candidate_ids = list_candidate_article_ids(connection, report_date)
    review_rows = connection.execute(
        """
        SELECT ira.* FROM issue_review_assessments ira
        JOIN briefings b ON b.id = ira.briefing_id
        WHERE b.report_date = ?
        """,
        (report_date,),
    ).fetchall()
    reviews = {row["issue_id"]: row for row in review_rows}
    rows = connection.execute("SELECT * FROM issues ORDER BY last_seen_at DESC, id").fetchall()
    result = []
    for row in rows:
        serialized = _serialize_issue(connection, row)
        if candidate_ids.intersection(serialized["articleIds"]):
            review = reviews.get(row["id"])
            serialized.update({
                "autoReviewScore": review["auto_score"] if review else None,
                "autoReviewRank": review["auto_rank"] if review else None,
                "autoReviewStars": review["auto_stars"] if review else None,
                "editorReviewStars": review["editor_stars"] if review else None,
                "editorReviewReason": (review["editor_reason"] or "") if review else "",
                "effectiveReviewStars": (review["editor_stars"] or review["auto_stars"]) if review else None,
                "reviewReasons": json.loads(review["reasons_json"] or "{}") if review else {},
                "reviewScoringVersion": review["scoring_version"] if review else None,
            })
            result.append(serialized)
    return sorted(result, key=lambda item: (-(item.get("effectiveReviewStars") or 0), item.get("autoReviewRank") or 999999, item.get("id") or ""))


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


def _enforce_manual_group_exclusivity(
    connection: sqlite3.Connection, report_date: str
) -> None:
    manual_members = connection.execute(
        """
        SELECT imo.issue_id, imo.article_id
        FROM issue_membership_overrides imo
        JOIN issues i ON i.id = imo.issue_id
        JOIN cluster_runs cr ON cr.id = i.last_cluster_run_id
        WHERE i.manual_group = 1 AND imo.action = 'add' AND cr.report_date = ?
        """,
        (report_date,),
    ).fetchall()
    issue_ids = [
        row["id"]
        for row in connection.execute(
            """
            SELECT i.id FROM issues i
            JOIN cluster_runs cr ON cr.id = i.last_cluster_run_id
            WHERE cr.report_date = ?
            """,
            (report_date,),
        ).fetchall()
    ]
    manual_issue_ids = {row["issue_id"] for row in manual_members}
    for manual_issue_id in manual_issue_ids:
        added_ids = {
            row["article_id"]
            for row in manual_members
            if row["issue_id"] == manual_issue_id
        }
        automatic_ids = connection.execute(
            """
            SELECT iaa.article_id
            FROM issue_auto_articles iaa
            JOIN issues i ON i.id = iaa.issue_id
            WHERE iaa.issue_id = ? AND iaa.cluster_run_id = i.last_cluster_run_id
            """,
            (manual_issue_id,),
        ).fetchall()
        for automatic in automatic_ids:
            if automatic["article_id"] not in added_ids:
                set_membership_override(
                    connection, manual_issue_id, automatic["article_id"], "remove"
                )
    for membership in manual_members:
        for issue_id in issue_ids:
            if issue_id == membership["issue_id"]:
                continue
            if membership["article_id"] in _effective_article_ids(connection, issue_id):
                set_membership_override(
                    connection, issue_id, membership["article_id"], "remove"
                )


def create_manual_group(
    connection: sqlite3.Connection, report_date: str, article_ids: list[str]
) -> str:
    unique_ids = list(dict.fromkeys(article_ids))
    if len(unique_ids) < 2:
        raise ValueError("manual group requires at least two articles")
    placeholders = ",".join("?" for _ in unique_ids)
    rows = connection.execute(
        f"""
        SELECT a.id, a.title, a.published_at,
               aa.auto_priority, aa.auto_priority_score, aa.auto_reasons_json
        FROM articles a
        LEFT JOIN article_assessments aa ON aa.article_id = a.id
        WHERE a.id IN ({placeholders})
        """,  # noqa: S608 - placeholders count only
        unique_ids,
    ).fetchall()
    if len(rows) != len(unique_ids):
        raise ValueError("article not found")
    representative = max(
        rows,
        key=lambda item: (
            item["auto_priority_score"] or 0,
            item["published_at"] or "",
            item["id"],
        ),
    )
    published = [row["published_at"] for row in rows if row["published_at"]]
    reasons = json.loads(representative["auto_reasons_json"] or "{}")
    issue_id = make_id()
    now = now_iso()
    latest_run = connection.execute(
        """
        SELECT id FROM cluster_runs
        WHERE report_date = ? AND status = 'applied'
        ORDER BY applied_at DESC, created_at DESC LIMIT 1
        """,
        (report_date,),
    ).fetchone()
    if latest_run is None:
        manual_run_id = make_id()
        connection.execute(
            """
            INSERT INTO cluster_runs (
                id, report_date, status, input_signature, proposal_json, diff_json,
                algorithm_version, created_at, applied_at
            ) VALUES (?, ?, 'applied', 'manual-group', '[]', '{}', 'manual-group-v1', ?, ?)
            """,
            (manual_run_id, report_date, now, now),
        )
        latest_run = {"id": manual_run_id}
    connection.execute(
        """
        INSERT INTO issues (
            id, representative_article_id, auto_title, auto_status, auto_priority,
            auto_priority_score, spread_score, auto_reasons_json, first_seen_at,
            last_seen_at, direct_mention, needs_review, last_cluster_run_id,
            manual_group, created_at, updated_at
        ) VALUES (?, ?, ?, 'new', ?, ?, 0, ?, ?, ?, ?, 1, ?, 1, ?, ?)
        """,
        (
            issue_id,
            representative["id"],
            representative["title"],
            representative["auto_priority"] or "reference",
            representative["auto_priority_score"] or 0,
            json.dumps({"manualGrouping": True}, ensure_ascii=False),
            min(published) if published else now,
            max(published) if published else now,
            1 if reasons.get("directMention") else 0,
            latest_run["id"] if latest_run else None,
            now,
            now,
        ),
    )
    existing_issue_ids = [
        row["id"]
        for row in connection.execute(
            """
            SELECT i.id FROM issues i
            JOIN cluster_runs cr ON cr.id = i.last_cluster_run_id
            WHERE i.id != ? AND cr.report_date = ?
            """,
            (issue_id, report_date),
        )
    ]
    for article_id in unique_ids:
        for existing_issue_id in existing_issue_ids:
            if article_id in _effective_article_ids(connection, existing_issue_id):
                set_membership_override(connection, existing_issue_id, article_id, "remove")
        set_membership_override(connection, issue_id, article_id, "add")
    quality_representative = _select_auto_representative(
        connection,
        unique_ids,
        fallback_id=representative["id"],
    )
    if quality_representative != representative["id"]:
        connection.execute(
            "UPDATE issues SET representative_article_id = ?, updated_at = ? WHERE id = ?",
            (quality_representative, now_iso(), issue_id),
        )
    return issue_id


def serialize_one(connection: sqlite3.Connection, issue_id: str) -> dict[str, Any] | None:
    row = get(connection, issue_id)
    return _serialize_issue(connection, row) if row else None


def _json_ids(value: str | None) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    return list(dict.fromkeys(str(item) for item in parsed if item)) if isinstance(parsed, list) else []


def _article_for_quality(connection: sqlite3.Connection, article_id: str) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT a.*, ao.raw_url AS observation_url, ao.raw_source AS observation_source,
               ao.provider AS observation_provider
        FROM articles a
        LEFT JOIN article_observations ao ON ao.id = (
            SELECT id FROM article_observations
            WHERE article_id = a.id ORDER BY observed_at DESC LIMIT 1
        )
        WHERE a.id = ?
        """,
        (article_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"], "title": row["title"], "source": row["source"],
        "url": row["observation_url"] or row["canonical_url"] or "",
        "pubDate": row["published_at"], "description": row["description"] or "",
        "bodyText": row["body_text"] or "", "bodyStatus": row["body_status"] or "missing",
        "bodyFetchedAt": row["body_fetched_at"], "bodyError": row["body_error"] or "",
        "publisherId": row["publisher_id"],
        "publisherAllowed": bool(row["publisher_allowed"]) if row["publisher_allowed"] is not None else None,
        "canonicalUrl": row["canonical_url"] or "", "sourceDomain": row["source_domain"] or "",
        "rawSource": row["observation_source"] or row["source"] or "",
        "provider": row["observation_provider"] or "",
    }


def _select_auto_representative(
    connection: sqlite3.Connection,
    article_ids: list[str],
    *,
    excluded_ids: list[str] | set[str] = (),
    fallback_id: str | None = None,
) -> str | None:
    excluded = set(excluded_ids)
    evaluated: list[tuple[dict[str, Any], dict[str, Any], bool]] = []
    for article_id in article_ids:
        if article_id in excluded:
            continue
        article = _article_for_quality(connection, article_id)
        if article is None:
            continue
        latest = latest_for_article(connection, article_id)
        evaluated.append((article, quality_for_article(connection, article), bool(latest or article["bodyText"])))
    if not any(item[2] for item in evaluated):
        return fallback_id if fallback_id in article_ids and fallback_id not in excluded else None
    eligible = [item for item in evaluated if item[1]["analysisEligible"]]
    if not eligible:
        return None
    return max(
        eligible,
        key=lambda item: (
            item[1]["contentQualityScore"],
            item[1]["extractionStatus"] == "success_full",
            item[0].get("pubDate") or "",
            item[0]["id"],
        ),
    )[0]["id"]


def list_evidence_articles(connection: sqlite3.Connection, issue_id: str) -> dict[str, Any] | None:
    issue = serialize_one(connection, issue_id)
    if issue is None:
        return None
    supplemental = set(issue["manualSupplementalArticleIds"])
    excluded = set(issue["manualExcludedArticleIds"])
    articles: list[dict[str, Any]] = []
    for article_id in issue["articleIds"]:
        article = _article_for_quality(connection, article_id)
        if article is None:
            continue
        quality = quality_for_article(connection, article)
        role = (
            "excluded" if article_id in excluded else
            "representative" if article_id == issue["representativeArticleId"] else
            "supplemental" if article_id in supplemental else "related"
        )
        articles.append({
            "articleId": article_id,
            "title": article["title"],
            "source": article["source"],
            "rawSource": quality.get("rawSource") or article.get("rawSource") or article["source"],
            "normalizedSource": quality.get("normalizedSource") or article["source"],
            "sourceDomain": quality.get("sourceDomain") or article.get("sourceDomain") or "",
            "canonicalUrl": quality.get("canonicalUrl") or article.get("url") or "",
            "pagePublisher": quality.get("pagePublisher") or "",
            "normalizationReason": quality.get("normalizationReason") or "",
            "url": article["url"],
            "publishedAt": article["pubDate"],
            "role": role,
            **quality,
        })
    role_order = {"representative": 0, "supplemental": 1, "related": 2, "excluded": 3}
    articles.sort(key=lambda item: (
        role_order[item["role"]],
        -int(item.get("contentQualityScore") or 0),
        item["articleId"],
    ))
    return {**issue, "articles": articles}


def list_articles_for_extraction(
    connection: sqlite3.Connection, issue_id: str
) -> list[dict[str, Any]] | None:
    if get(connection, issue_id) is None:
        return None
    return [
        article
        for article_id in _effective_article_ids(connection, issue_id)
        if (article := _article_for_quality(connection, article_id)) is not None
    ]


def update_evidence_selection(
    connection: sqlite3.Connection,
    issue_id: str,
    *,
    expected_revision: int,
    representative_article_id: str | None,
    supplemental_article_ids: list[str],
    excluded_article_ids: list[str],
) -> dict[str, Any]:
    row = get(connection, issue_id)
    if row is None:
        raise LookupError("issue")
    if int(row["evidence_revision"]) != expected_revision:
        raise RuntimeError("revision")
    members = _effective_article_ids(connection, issue_id)
    supplemental = list(dict.fromkeys(supplemental_article_ids))
    excluded = list(dict.fromkeys(excluded_article_ids))
    referenced = set(supplemental + excluded + ([representative_article_id] if representative_article_id else []))
    if not referenced.issubset(members):
        raise ValueError("membership")
    if len(supplemental) > 2:
        raise ValueError("supplemental_limit")
    if representative_article_id in excluded or set(supplemental).intersection(excluded):
        raise ValueError("excluded_role")
    if representative_article_id in supplemental:
        raise ValueError("duplicate_role")
    for article_id in [item for item in [representative_article_id, *supplemental] if item]:
        article = _article_for_quality(connection, article_id)
        if article is None or not quality_for_article(connection, article)["analysisEligible"]:
            raise PermissionError(article_id)
    automatic = _select_auto_representative(
        connection, members, excluded_ids=excluded, fallback_id=row["representative_article_id"]
    )
    now = now_iso()
    connection.execute(
        """
        UPDATE issues SET representative_article_id = ?, manual_representative_article_id = ?,
            manual_supplemental_article_ids_json = ?, manual_excluded_article_ids_json = ?,
            manual_selection_updated_at = ?, evidence_revision = evidence_revision + 1,
            updated_at = ?
        WHERE id = ? AND evidence_revision = ?
        """,
        (
            automatic, representative_article_id,
            json.dumps(supplemental, ensure_ascii=False),
            json.dumps(excluded, ensure_ascii=False), now, now, issue_id, expected_revision,
        ),
    )
    return list_evidence_articles(connection, issue_id)


def refresh_auto_representatives_for_article(
    connection: sqlite3.Connection, article_id: str
) -> list[str]:
    changed: list[str] = []
    for row in connection.execute("SELECT * FROM issues ORDER BY id").fetchall():
        members = _effective_article_ids(connection, row["id"])
        if article_id not in members:
            continue
        representative = _select_auto_representative(
            connection,
            members,
            excluded_ids=_json_ids(row["manual_excluded_article_ids_json"]),
            fallback_id=row["representative_article_id"],
        )
        if representative != row["representative_article_id"]:
            connection.execute(
                "UPDATE issues SET representative_article_id = ?, updated_at = ? WHERE id = ?",
                (representative, now_iso(), row["id"]),
            )
            changed.append(row["id"])
    return changed


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
    briefing = connection.execute(
        "SELECT id FROM briefings WHERE report_date = ?", (report_date,)
    ).fetchone()
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
        manual_representative_id = article_id_map.get(
            snapshot.get("manualRepresentativeArticleId")
        )
        supplemental_ids = [
            article_id_map[article_id]
            for article_id in snapshot.get("manualSupplementalArticleIds", [])
            if article_id in article_id_map
        ][:2]
        excluded_ids = [
            article_id_map[article_id]
            for article_id in snapshot.get("manualExcludedArticleIds", [])
            if article_id in article_id_map
        ]
        connection.execute(
            """
            INSERT INTO issues (
                id, representative_article_id, auto_title, editor_title, auto_status,
                editor_status, auto_priority, editor_priority, auto_priority_score,
                spread_score, auto_reasons_json, first_seen_at, last_seen_at,
                direct_mention, needs_review, last_cluster_run_id, manual_group,
                manual_representative_article_id,
                manual_supplemental_article_ids_json,
                manual_excluded_article_ids_json, manual_selection_updated_at,
                evidence_revision, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                issue_id, representative_id, snapshot.get("autoTitle"), snapshot.get("editorTitle"),
                snapshot.get("autoStatus"), snapshot.get("editorStatus"), snapshot.get("autoPriority"),
                snapshot.get("editorPriority"), snapshot.get("autoPriorityScore"),
                snapshot.get("spreadScore", 0),
                json.dumps(snapshot.get("autoReasons") or {}, ensure_ascii=False),
                snapshot.get("firstSeenAt"), snapshot.get("lastSeenAt"),
                1 if snapshot.get("directMention") else 0, 1 if snapshot.get("needsReview") else 0,
                run_id, 1 if snapshot.get("manualGroup") else 0,
                manual_representative_id,
                json.dumps(supplemental_ids, ensure_ascii=False),
                json.dumps(excluded_ids, ensure_ascii=False),
                snapshot.get("manualSelectionUpdatedAt"),
                int(snapshot.get("evidenceRevision") or 0), now, now,
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
        if briefing is not None:
            connection.execute(
                """
                INSERT INTO issue_review_assessments (
                    briefing_id, issue_id, auto_score, auto_rank, auto_stars,
                    editor_stars, editor_reason, reasons_json, scoring_version,
                    calculated_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    briefing["id"], issue_id, snapshot.get("autoReviewScore"),
                    snapshot.get("autoReviewRank"), snapshot.get("autoReviewStars"),
                    snapshot.get("editorReviewStars"), snapshot.get("editorReviewReason") or None,
                    json.dumps(snapshot.get("reviewReasons") or {}, ensure_ascii=False),
                    snapshot.get("reviewScoringVersion") or "review-v1", now, now,
                ),
            )
            connection.execute(
                """
                INSERT INTO briefing_issues (
                    briefing_id, issue_id, selected, starred, note, sort_order,
                    direct_coverage_override, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    briefing["id"],
                    issue_id,
                    1 if snapshot.get("selected") else 0,
                    1 if snapshot.get("starred") else 0,
                    snapshot.get("note") or None,
                    snapshot.get("sortOrder") or 0,
                    (
                        1 if snapshot.get("editorDirectCoverage") is True
                        else 0 if snapshot.get("editorDirectCoverage") is False
                        else None
                    ),
                    now,
                    now,
                ),
            )
        imported += 1
    _enforce_manual_group_exclusivity(connection, report_date)
    return imported
