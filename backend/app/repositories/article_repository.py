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
    auto_category: str | None,
    auto_risk: str | None,
    auto_risk_score: int | None,
    auto_sentiment: str | None,
    auto_reasons: list[str] | None,
    classifier_version: str,
) -> None:
    now = now_iso()
    connection.execute(
        """
        INSERT INTO article_assessments (
            article_id, auto_category, auto_risk, auto_risk_score, auto_sentiment,
            auto_reasons_json, classifier_version, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(article_id) DO UPDATE SET
            auto_category = excluded.auto_category,
            auto_risk = excluded.auto_risk,
            auto_risk_score = excluded.auto_risk_score,
            auto_sentiment = excluded.auto_sentiment,
            auto_reasons_json = excluded.auto_reasons_json,
            classifier_version = excluded.classifier_version,
            updated_at = excluded.updated_at
        """,
        (
            article_id,
            auto_category,
            auto_risk,
            auto_risk_score,
            auto_sentiment,
            json.dumps(auto_reasons or [], ensure_ascii=False),
            classifier_version,
            now,
        ),
    )


_CANDIDATE_UNION_SQL = """
WITH candidate_ids AS (
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
),
latest_observation AS (
    SELECT article_id, raw_url, provider
    FROM (
        SELECT article_id, raw_url, provider,
               ROW_NUMBER() OVER (PARTITION BY article_id ORDER BY observed_at DESC) AS rn
        FROM article_observations
    )
    WHERE rn = 1
)
SELECT
    a.id AS id,
    a.title AS title,
    a.source AS source,
    a.published_at AS published_at,
    a.description AS description,
    a.category_hint AS category_hint,
    a.manual AS manual,
    lo.raw_url AS url,
    lo.provider AS provider,
    aa.auto_risk AS auto_risk,
    aa.auto_risk_score AS auto_risk_score,
    aa.auto_sentiment AS auto_sentiment,
    aa.auto_reasons_json AS auto_reasons_json,
    ba.selected AS selected,
    ba.starred AS starred,
    ba.note AS note,
    ba.dismissed AS dismissed,
    ba.sort_order AS sort_order
FROM candidate_ids ci
JOIN articles a ON a.id = ci.article_id
LEFT JOIN latest_observation lo ON lo.article_id = a.id
LEFT JOIN article_assessments aa ON aa.article_id = a.id
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
        result.append(
            {
                "id": row["id"],
                "title": row["title"],
                "source": row["source"],
                "url": row["url"] or "",
                "pubDate": row["published_at"],
                "description": row["description"] or "",
                "category": row["category_hint"],
                "manual": bool(row["manual"]),
                "risk": row["auto_risk"],
                "riskScore": row["auto_risk_score"],
                "sentiment": row["auto_sentiment"],
                "matchedKeywords": json.loads(row["auto_reasons_json"]) if row["auto_reasons_json"] else [],
                "included": bool(row["selected"]) if row["selected"] is not None else False,
                "starred": bool(row["starred"]) if row["starred"] is not None else False,
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


def delete_article(connection: sqlite3.Connection, article_id: str) -> None:
    connection.execute("DELETE FROM article_observations WHERE article_id = ?", (article_id,))
    connection.execute("DELETE FROM article_assessments WHERE article_id = ?", (article_id,))
    connection.execute("DELETE FROM briefing_articles WHERE article_id = ?", (article_id,))
    connection.execute("DELETE FROM articles WHERE id = ?", (article_id,))
