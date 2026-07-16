from __future__ import annotations

import json
import sqlite3
from typing import Any
from urllib.parse import urlsplit

from backend.app.core.clock import now_iso
from backend.app.services.deduplication.fuzzy import bigram_similarity
from backend.app.services.ids import make_id
from backend.app.services.normalization.content_key import make_content_key
from backend.app.services.normalization.dates import date_value
from backend.app.services.normalization.title import normalized_article_title
from backend.app.services.normalization.url import canonical_article_url


def _source_domain(url: str | None) -> str:
    try:
        return (urlsplit(str(url or "")).hostname or "").lower()
    except ValueError:
        return ""


def find_by_content_key(connection: sqlite3.Connection, content_key: str) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT * FROM articles WHERE content_key = ?", (content_key,)
    ).fetchone()


def get_article(connection: sqlite3.Connection, article_id: str) -> sqlite3.Row | None:
    return connection.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()


def find_recent_candidates(
    connection: sqlite3.Connection, since_iso: str
) -> list[sqlite3.Row]:
    """fuzzy 매칭 대상 범위를 좁히기 위해 published_at이 since_iso 이후인 기사만 조회한다."""
    return connection.execute(
        "SELECT * FROM articles WHERE published_at IS NULL OR published_at >= ?",
        (since_iso,),
    ).fetchall()


def find_matching_article(
    connection: sqlite3.Connection,
    *,
    url: str | None,
    title: str,
    published_at: str | None,
    since_iso: str,
) -> sqlite3.Row | None:
    """canonical URL 정확매칭 우선, 없으면 최근 후보 중 제목 fuzzy 매칭(services.deduplication.service.same_article와 동일 규칙)."""
    canonical = canonical_article_url(url)
    if canonical:
        row = connection.execute(
            "SELECT * FROM articles WHERE canonical_url = ?", (canonical,)
        ).fetchone()
        if row is not None:
            return row

    normalized_title = normalized_article_title(title)
    if not normalized_title:
        return None
    candidate_pub_value = date_value(published_at)
    for row in find_recent_candidates(connection, since_iso):
        row_title = row["normalized_title"] or ""
        if not row_title:
            continue
        if row_title == normalized_title:
            return row
        if min(len(row_title), len(normalized_title)) < 16:
            continue
        row_pub_value = date_value(row["published_at"])
        if candidate_pub_value and row_pub_value and abs(candidate_pub_value - row_pub_value) > 72 * 3600000:
            continue
        if bigram_similarity(row_title, normalized_title) >= 0.9:
            return row
    return None


def create_article(
    connection: sqlite3.Connection,
    *,
    url: str | None,
    title: str,
    source: str | None,
    published_at: str | None,
    description: str | None,
    category_hint: str | None,
    manual: bool,
) -> str:
    article_id = make_id()
    now = now_iso()
    canonical_url = canonical_article_url(url)
    content_key = make_content_key(url, title, source, published_at)
    connection.execute(
        """
        INSERT INTO articles (
            id, content_key, canonical_url, title, normalized_title, source, source_domain,
            published_at, first_observed_at, last_observed_at, description, body_status,
            category_hint, manual, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            article_id,
            content_key,
            canonical_url,
            title,
            normalized_article_title(title),
            source,
            _source_domain(url),
            published_at,
            now,
            now,
            description or "",
            "missing",
            category_hint,
            1 if manual else 0,
            now,
            now,
        ),
    )
    return article_id


def touch_article(
    connection: sqlite3.Connection,
    article_id: str,
    *,
    description: str | None = None,
    canonical_url: str | None = None,
) -> None:
    now = now_iso()
    if description is not None:
        connection.execute(
            "UPDATE articles SET last_observed_at = ?, description = ?, updated_at = ? WHERE id = ?",
            (now, description, now, article_id),
        )
    else:
        connection.execute(
            "UPDATE articles SET last_observed_at = ?, updated_at = ? WHERE id = ?",
            (now, now, article_id),
        )


def update_article_body(
    connection: sqlite3.Connection,
    article_id: str,
    *,
    body_text: str,
    body_status: str,
    body_error: str,
    fetched_at: str | None = None,
) -> None:
    now = now_iso()
    connection.execute(
        """
        UPDATE articles
        SET body_text = ?, body_status = ?, body_fetched_at = ?, body_error = ?, updated_at = ?
        WHERE id = ?
        """,
        (body_text, body_status, fetched_at or now, body_error, now, article_id),
    )


def insert_observation(
    connection: sqlite3.Connection,
    *,
    article_id: str,
    collection_run_provider_id: str | None,
    provider: str,
    provider_item_key: str | None,
    query_group_id: str | None,
    raw_url: str | None,
    raw_title: str | None,
    raw_source: str | None,
    raw_published_at: str | None,
    raw_description: str | None,
    raw_payload_json: str | None,
    dedup_method: str,
    dedup_score: float | None,
) -> str:
    observation_id = make_id()
    connection.execute(
        """
        INSERT INTO article_observations (
            id, article_id, collection_run_provider_id, provider, provider_item_key,
            query_group_id, raw_url, raw_title, raw_source, raw_published_at, raw_description,
            raw_payload_json, observed_at, dedup_method, dedup_score
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            observation_id,
            article_id,
            collection_run_provider_id,
            provider,
            provider_item_key,
            query_group_id,
            raw_url,
            raw_title,
            raw_source,
            raw_published_at,
            raw_description,
            raw_payload_json,
            now_iso(),
            dedup_method,
            dedup_score,
        ),
    )
    return observation_id


def upsert_assessment(
    connection: sqlite3.Connection,
    *,
    article_id: str,
    assessment: dict[str, Any],
    classifier_version: str,
) -> None:
    now = now_iso()
    priority = assessment.get("autoPriority")
    legacy_risk = {"required": "critical", "review": "watch", "reference": "routine"}.get(priority)
    connection.execute(
        """
        INSERT INTO article_assessments (
            article_id, auto_category, auto_risk, auto_risk_score, auto_sentiment,
            auto_reasons_json, classifier_version, updated_at, auto_event_type,
            auto_relevance_score, auto_severity_score, auto_priority_score,
            auto_priority, auto_tone, incident_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(article_id) DO UPDATE SET
            auto_category = excluded.auto_category,
            auto_risk = excluded.auto_risk,
            auto_risk_score = excluded.auto_risk_score,
            auto_sentiment = excluded.auto_sentiment,
            auto_reasons_json = excluded.auto_reasons_json,
            classifier_version = excluded.classifier_version,
            auto_event_type = excluded.auto_event_type,
            auto_relevance_score = excluded.auto_relevance_score,
            auto_severity_score = excluded.auto_severity_score,
            auto_priority_score = excluded.auto_priority_score,
            auto_priority = excluded.auto_priority,
            auto_tone = excluded.auto_tone,
            incident_json = excluded.incident_json,
            updated_at = excluded.updated_at
        """,
        (
            article_id,
            assessment.get("autoCategory"),
            legacy_risk,
            assessment.get("autoSeverityScore"),
            assessment.get("autoTone"),
            json.dumps(assessment.get("autoReasons") or {}, ensure_ascii=False),
            classifier_version,
            now,
            assessment.get("autoEventType"),
            assessment.get("autoRelevanceScore"),
            assessment.get("autoSeverityScore"),
            assessment.get("autoPriorityScore"),
            priority,
            assessment.get("autoTone"),
            json.dumps(assessment.get("incident"), ensure_ascii=False)
            if assessment.get("incident") is not None
            else None,
        ),
    )


def get_assessment(connection: sqlite3.Connection, article_id: str) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT * FROM article_assessments WHERE article_id = ?", (article_id,)
    ).fetchone()


def patch_final_assessment(
    connection: sqlite3.Connection, article_id: str, patch: dict[str, str | None]
) -> sqlite3.Row:
    column_by_field = {
        "finalCategory": "final_category",
        "finalEventType": "final_event_type",
        "finalPriority": "final_priority",
        "finalTone": "final_tone",
    }
    assignments = [f"{column_by_field[field]} = ?" for field in patch]
    values = [patch[field] for field in patch]
    if assignments:
        connection.execute(
            f"UPDATE article_assessments SET {', '.join(assignments)}, updated_at = ? WHERE article_id = ?",  # noqa: S608 - columns are fixed above
            (*values, now_iso(), article_id),
        )
    connection.execute(
        """
        UPDATE article_assessments
        SET manual_override = CASE
            WHEN final_category IS NOT NULL OR final_event_type IS NOT NULL
              OR final_priority IS NOT NULL OR final_tone IS NOT NULL THEN 1 ELSE 0 END,
            updated_at = ?
        WHERE article_id = ?
        """,
        (now_iso(), article_id),
    )
    return get_assessment(connection, article_id)


def assessment_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    reasons = json.loads(row["auto_reasons_json"]) if row["auto_reasons_json"] else {}
    auto_priority = row["auto_priority"]
    auto_tone = row["auto_tone"] or row["auto_sentiment"]
    auto_category = row["auto_category"]
    auto_event_type = row["auto_event_type"]
    incident = json.loads(row["incident_json"]) if row["incident_json"] else None
    return {
        "autoCategory": auto_category,
        "autoEventType": auto_event_type,
        "autoRelevanceScore": row["auto_relevance_score"],
        "autoSeverityScore": row["auto_severity_score"],
        "autoPriorityScore": row["auto_priority_score"],
        "autoPriority": auto_priority,
        "autoTone": auto_tone,
        "autoReasons": reasons,
        "incident": incident,
        "finalCategory": row["final_category"],
        "finalEventType": row["final_event_type"],
        "finalPriority": row["final_priority"],
        "finalTone": row["final_tone"],
        "manualOverride": bool(row["manual_override"]),
        "effectiveCategory": row["final_category"] or auto_category,
        "effectiveEventType": row["final_event_type"] or auto_event_type,
        "effectivePriority": row["final_priority"] or auto_priority,
        "effectiveTone": row["final_tone"] or auto_tone,
        "classifierVersion": row["classifier_version"],
    }


CANDIDATE_IDS_SQL = """
SELECT ao.article_id AS article_id
FROM article_observations ao
JOIN collection_run_providers crp ON crp.id = ao.collection_run_provider_id
JOIN collection_runs cr ON cr.id = crp.collection_run_id
WHERE cr.report_date = :report_date
UNION
SELECT ba.article_id AS article_id
FROM briefing_articles ba
JOIN briefings b ON b.id = ba.briefing_id
WHERE b.report_date = :report_date
"""


def list_candidate_article_ids(connection: sqlite3.Connection, report_date: str) -> set[str]:
    rows = connection.execute(CANDIDATE_IDS_SQL, {"report_date": report_date}).fetchall()
    return {row["article_id"] for row in rows}


_CANDIDATE_UNION_SQL = f"""
WITH candidate_ids AS ({CANDIDATE_IDS_SQL}),
latest_observation AS (
    SELECT article_id, raw_url, provider
    FROM (
        SELECT article_id, raw_url, provider,
               ROW_NUMBER() OVER (PARTITION BY article_id ORDER BY observed_at DESC) AS rn
        FROM article_observations
    )
    WHERE rn = 1
),
matched_queries AS (
    SELECT article_id, GROUP_CONCAT(DISTINCT query_group_id) AS query_group_ids
    FROM article_observations
    WHERE query_group_id IS NOT NULL AND query_group_id != ''
    GROUP BY article_id
)
SELECT
    a.id AS id,
    a.content_key AS content_key,
    a.title AS title,
    a.source AS source,
    a.published_at AS published_at,
    a.description AS description,
    a.body_text AS body_text,
    a.body_status AS body_status,
    a.body_fetched_at AS body_fetched_at,
    a.body_error AS body_error,
    a.category_hint AS category_hint,
    a.manual AS manual,
    lo.raw_url AS url,
    lo.provider AS provider,
    aa.auto_risk AS auto_risk,
    aa.auto_risk_score AS auto_risk_score,
    aa.auto_sentiment AS auto_sentiment,
    aa.auto_reasons_json AS auto_reasons_json,
    aa.auto_category AS auto_category,
    aa.auto_event_type AS auto_event_type,
    aa.auto_relevance_score AS auto_relevance_score,
    aa.auto_severity_score AS auto_severity_score,
    aa.auto_priority_score AS auto_priority_score,
    aa.auto_priority AS auto_priority,
    aa.auto_tone AS auto_tone,
    aa.final_category AS final_category,
    aa.final_event_type AS final_event_type,
    aa.final_priority AS final_priority,
    aa.final_tone AS final_tone,
    aa.manual_override AS manual_override,
    aa.classifier_version AS classifier_version,
    aa.incident_json AS incident_json,
    mq.query_group_ids AS query_group_ids,
    ba.selected AS selected,
    ba.starred AS starred,
    ba.top_issue AS top_issue,
    ba.note AS note,
    ba.dismissed AS dismissed,
    ba.sort_order AS sort_order
FROM candidate_ids ci
JOIN articles a ON a.id = ci.article_id
LEFT JOIN latest_observation lo ON lo.article_id = a.id
LEFT JOIN article_assessments aa ON aa.article_id = a.id
LEFT JOIN matched_queries mq ON mq.article_id = a.id
LEFT JOIN briefings b ON b.report_date = :report_date
LEFT JOIN briefing_articles ba ON ba.briefing_id = b.id AND ba.article_id = a.id
"""


def list_candidates(
    connection: sqlite3.Connection, report_date: str, include_dismissed: bool
) -> list[dict[str, Any]]:
    rows = connection.execute(_CANDIDATE_UNION_SQL, {"report_date": report_date}).fetchall()
    result = []
    for row in rows:
        dismissed = bool(row["dismissed"])
        if not include_dismissed and dismissed:
            continue
        assessment = assessment_to_dict(row) if row["classifier_version"] else None
        effective_priority = assessment["effectivePriority"] if assessment else None
        effective_tone = assessment["effectiveTone"] if assessment else row["auto_sentiment"]
        effective_category = assessment["effectiveCategory"] if assessment else row["category_hint"]
        reasons = assessment["autoReasons"] if assessment else {}
        result.append(
            {
                "id": row["id"],
                "contentKey": row["content_key"],
                "title": row["title"],
                "source": row["source"],
                "url": row["url"] or "",
                "pubDate": row["published_at"],
                "description": row["description"] or "",
                "bodyText": row["body_text"] or "",
                "bodyStatus": row["body_status"] or "missing",
                "bodyFetchedAt": row["body_fetched_at"],
                "bodyError": row["body_error"] or "",
                "category": effective_category,
                "manual": bool(row["manual"]),
                "risk": {"required": "critical", "review": "watch", "reference": "routine"}.get(effective_priority, row["auto_risk"]),
                "riskScore": row["auto_severity_score"] if row["auto_severity_score"] is not None else row["auto_risk_score"],
                "sentiment": effective_tone,
                "eventType": assessment["effectiveEventType"] if assessment else None,
                "priority": effective_priority,
                "relevanceScore": row["auto_relevance_score"],
                "severityScore": row["auto_severity_score"],
                "priorityScore": row["auto_priority_score"],
                "assessment": assessment,
                "incident": assessment["incident"] if assessment else None,
                "matchedQueryIds": sorted(
                    query_id for query_id in (row["query_group_ids"] or "").split(",") if query_id
                ),
                "matchedKeywords": reasons.get("matchedTerms", []) if isinstance(reasons, dict) else reasons,
                "included": bool(row["selected"]) if row["selected"] is not None else False,
                "starred": bool(row["starred"]) if row["starred"] is not None else False,
                "topIssue": bool(row["top_issue"]) if row["top_issue"] is not None else False,
                "note": row["note"] or "",
                "dismissed": dismissed,
                "sortOrder": row["sort_order"],
            }
        )
    return result


def count_briefing_references(connection: sqlite3.Connection, article_id: str) -> int:
    row = connection.execute(
        "SELECT COUNT(DISTINCT briefing_id) AS count FROM briefing_articles WHERE article_id = ?",
        (article_id,),
    ).fetchone()
    return int(row["count"])


def count_final_snapshot_references(connection: sqlite3.Connection, article_id: str) -> int:
    row = connection.execute(
        "SELECT COUNT(*) AS count FROM briefing_versions WHERE snapshot_json LIKE ?",
        (f'%"{article_id}"%',),
    ).fetchone()
    return int(row["count"])


def count_issue_references(connection: sqlite3.Connection, article_id: str) -> int:
    row = connection.execute(
        """
        SELECT (
            (SELECT COUNT(*) FROM issue_auto_articles WHERE article_id = ?)
          + (SELECT COUNT(*) FROM issue_membership_overrides WHERE article_id = ?)
        ) AS count
        """,
        (article_id, article_id),
    ).fetchone()
    return int(row["count"])


def count_ai_references(connection: sqlite3.Connection, article_id: str) -> int:
    row = connection.execute(
        "SELECT COUNT(*) AS count FROM ai_runs WHERE evidence_json LIKE ?",
        (f'%"{article_id}"%',),
    ).fetchone()
    return int(row["count"])


def delete_article(connection: sqlite3.Connection, article_id: str) -> None:
    connection.execute("DELETE FROM article_observations WHERE article_id = ?", (article_id,))
    connection.execute("DELETE FROM article_assessments WHERE article_id = ?", (article_id,))
    connection.execute("DELETE FROM briefing_articles WHERE article_id = ?", (article_id,))
    connection.execute("DELETE FROM articles WHERE id = ?", (article_id,))
