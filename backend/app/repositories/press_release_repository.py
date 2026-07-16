from __future__ import annotations

import json
import sqlite3
from typing import Any

from backend.app.core.clock import now_iso


def upsert_release(connection: sqlite3.Connection, release: dict[str, Any]) -> None:
    now = now_iso()
    connection.execute(
        """
        INSERT INTO kesco_press_releases (
            id, bbs_seq, title, published_at, body_text, canonical_url,
            fetched_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            title = excluded.title,
            published_at = excluded.published_at,
            body_text = CASE
                WHEN length(excluded.body_text) >= length(kesco_press_releases.body_text)
                THEN excluded.body_text ELSE kesco_press_releases.body_text END,
            canonical_url = excluded.canonical_url,
            fetched_at = excluded.fetched_at,
            updated_at = excluded.updated_at
        """,
        (
            release["id"],
            release["bbsSeq"],
            release["title"],
            release.get("publishedAt"),
            release.get("bodyText") or "",
            release["url"],
            release.get("fetchedAt") or now,
            now,
            now,
        ),
    )


def list_recent(connection: sqlite3.Connection, limit: int = 60) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT id, bbs_seq, title, published_at, body_text, canonical_url, fetched_at
        FROM kesco_press_releases
        ORDER BY published_at DESC, bbs_seq DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [
        {
            "id": row["id"],
            "bbsSeq": row["bbs_seq"],
            "title": row["title"],
            "publishedAt": row["published_at"],
            "bodyText": row["body_text"] or "",
            "url": row["canonical_url"],
            "fetchedAt": row["fetched_at"],
        }
        for row in rows
    ]


def cache_status(connection: sqlite3.Connection) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT COUNT(*) AS release_count,
               MAX(fetched_at) AS last_fetched_at,
               MAX(published_at) AS latest_published_at
        FROM kesco_press_releases
        """
    ).fetchone()
    return {
        "releaseCount": int(row["release_count"] or 0),
        "lastFetchedAt": row["last_fetched_at"],
        "latestPublishedAt": row["latest_published_at"],
    }


def upsert_origin(
    connection: sqlite3.Connection,
    article_id: str,
    assessment: dict[str, Any],
    classifier_version: str,
) -> None:
    connection.execute(
        """
        INSERT INTO article_origin_assessments (
            article_id, auto_origin_type, auto_press_release_id, auto_confidence,
            auto_reasons_json, classifier_version, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(article_id) DO UPDATE SET
            auto_origin_type = excluded.auto_origin_type,
            auto_press_release_id = excluded.auto_press_release_id,
            auto_confidence = excluded.auto_confidence,
            auto_reasons_json = excluded.auto_reasons_json,
            classifier_version = excluded.classifier_version,
            updated_at = excluded.updated_at
        """,
        (
            article_id,
            assessment["originType"],
            assessment["pressReleaseId"],
            assessment["confidence"],
            json.dumps(assessment.get("reasons") or {}, ensure_ascii=False),
            classifier_version,
            now_iso(),
        ),
    )


def serialize_origin_row(row: sqlite3.Row) -> dict[str, Any] | None:
    if not row["origin_auto_type"]:
        return None
    effective_type = row["origin_final_type"] or row["origin_auto_type"]
    effective_release_id = row["origin_final_release_id"] or row["origin_auto_release_id"]
    if effective_type == "independent":
        effective_release_id = None
    return {
        "autoType": row["origin_auto_type"],
        "finalType": row["origin_final_type"],
        "effectiveType": effective_type,
        "pressReleaseId": effective_release_id,
        "confidence": row["origin_confidence"],
        "reasons": json.loads(row["origin_reasons_json"] or "{}"),
        "manualOverride": bool(row["origin_manual_override"]),
        "pressRelease": {
            "id": row["press_release_id"],
            "bbsSeq": row["press_release_bbs_seq"],
            "title": row["press_release_title"],
            "publishedAt": row["press_release_published_at"],
            "bodyText": row["press_release_body_text"] or "",
            "url": row["press_release_url"],
            "fetchedAt": row["press_release_fetched_at"],
        }
        if row["press_release_id"]
        else None,
    }


def import_origin(
    connection: sqlite3.Connection,
    article_id: str,
    origin: dict[str, Any],
) -> None:
    release = origin.get("pressRelease") or {}
    release_id = release.get("id") or origin.get("pressReleaseId")
    effective_type = origin.get("effectiveType") or origin.get("autoType")
    if not release_id:
        return
    bbs_seq = str(release.get("bbsSeq") or str(release_id).removeprefix("kesco:"))
    upsert_release(
        connection,
        {
            "id": release_id,
            "bbsSeq": bbs_seq,
            "title": release.get("title") or "KESCO 보도자료",
            "publishedAt": release.get("publishedAt"),
            "bodyText": release.get("bodyText") or "",
            "url": release.get("url")
            or f"https://www.kesco.or.kr/bbs/pr/selectBbs.do?bbs_code=MKB00002&bbs_seq={bbs_seq}",
            "fetchedAt": release.get("fetchedAt") or now_iso(),
        },
    )
    auto_type = origin.get("autoType") or effective_type
    if auto_type not in {"kesco_republication", "kesco_based"}:
        auto_type = "kesco_based"
    upsert_origin(
        connection,
        article_id,
        {
            "originType": auto_type,
            "pressReleaseId": release_id,
            "confidence": float(origin.get("confidence") or 0),
            "reasons": origin.get("reasons") or {"imported": True},
        },
        "json-import",
    )
    final_type = origin.get("finalType")
    if final_type is not None:
        connection.execute(
            """
            UPDATE article_origin_assessments
            SET final_origin_type = ?, final_press_release_id = ?,
                manual_override = ?, updated_at = ?
            WHERE article_id = ?
            """,
            (
                final_type,
                None if final_type == "independent" else release_id,
                1 if origin.get("manualOverride") else 0,
                now_iso(),
                article_id,
            ),
        )
