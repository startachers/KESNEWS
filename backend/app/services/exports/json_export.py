from __future__ import annotations

import sqlite3
from typing import Any

from backend.app.core.clock import now_iso
from backend.app.repositories import article_repository as article_repo
from backend.app.repositories import ai_run_repository as ai_run_repo
from backend.app.repositories import briefing_repository as briefing_repo
from backend.app.repositories import issue_repository as issue_repo
from backend.app.repositories.database import backup_database
from backend.app.services.classification.service import CLASSIFIER_VERSION, classify_article
from backend.app.services.normalization.dates import since_bound_iso

SCHEMA_VERSION = 3
SUPPORTED_SCHEMA_VERSIONS = {1, 2, 3}

_BRIEFING_EXPORT_FIELDS = {
    "preparedBy": "prepared_by",
    "status": "status",
    "situationSummary": "situation_summary",
    "actionNote": "action_note",
    "summaryMode": "summary_mode",
    "aiModel": "ai_model",
    "aiPromptVersion": "ai_prompt_version",
    "aiGeneratedAt": "ai_generated_at",
    "aiInputSignature": "ai_input_signature",
}


class SchemaUnsupported(Exception):
    pass


class ImportConflict(Exception):
    def __init__(self, details: dict[str, Any]):
        super().__init__("import conflict")
        self.details = details


def build_export(connection: sqlite3.Connection, report_date: str) -> dict[str, Any] | None:
    briefing = briefing_repo.get_by_date(connection, report_date)
    if briefing is None:
        return None
    articles = article_repo.list_candidates(connection, report_date, include_dismissed=True)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "reportDate": report_date,
        "exportedAt": now_iso(),
        "briefing": {key: briefing[column] for key, column in _BRIEFING_EXPORT_FIELDS.items()},
        "articles": articles,
        "issues": issue_repo.list_for_report_date(connection, report_date),
        "aiRuns": [
            ai_run_repo.serialize(row)
            for row in ai_run_repo.list_for_briefing(connection, briefing["id"])
        ],
    }


def import_export(
    connection: sqlite3.Connection, report_date: str, payload: dict[str, Any], mode: str | None
) -> dict[str, Any]:
    schema_version = payload.get("schemaVersion")
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise SchemaUnsupported()

    existing = briefing_repo.get_by_date(connection, report_date)
    if existing is not None and mode != "replace":
        raise ImportConflict({"existingRevision": existing["revision"]})

    if existing is not None and mode == "replace":
        backup_database()
        connection.execute("DELETE FROM ai_runs WHERE briefing_id = ?", (existing["id"],))
        connection.execute("DELETE FROM briefing_articles WHERE briefing_id = ?", (existing["id"],))

    expected_revision = existing["revision"] if existing is not None else 0
    briefing_patch = payload.get("briefing") or {}
    briefing = briefing_repo.create_or_update(connection, report_date, expected_revision, briefing_patch)

    imported_articles = payload.get("articles") or []
    article_id_map: dict[str, str] = {}
    for index, article in enumerate(imported_articles):
        content_key = article.get("contentKey")
        match = article_repo.find_by_content_key(connection, content_key) if content_key else None
        if match is None:
            since = since_bound_iso(article.get("pubDate"), 24 * 365)
            match = article_repo.find_matching_article(
                connection,
                url=article.get("url"),
                title=article.get("title") or "",
                published_at=article.get("pubDate"),
                since_iso=since,
            )

        if match is not None:
            article_id = match["id"]
        else:
            article_id = article_repo.create_article(
                connection,
                url=article.get("url"),
                title=article.get("title") or "제목 없음",
                source=article.get("source"),
                published_at=article.get("pubDate"),
                description=article.get("description"),
                category_hint=article.get("category"),
                manual=True,
            )
            article_repo.insert_observation(
                connection,
                article_id=article_id,
                collection_run_provider_id=None,
                provider="import",
                provider_item_key=None,
                query_group_id=None,
                raw_url=article.get("url"),
                raw_title=article.get("title"),
                raw_source=article.get("source"),
                raw_published_at=article.get("pubDate"),
                raw_description=article.get("description"),
                raw_payload_json=None,
                dedup_method="new",
                dedup_score=None,
            )

        classified = classify_article(
            {
                "title": article.get("title") or "",
                "description": article.get("description") or "",
                "category": article.get("category"),
            }
        )
        article_repo.upsert_assessment(
            connection,
            article_id=article_id,
            assessment=(article.get("assessment") or classified["assessment"]),
            classifier_version=CLASSIFIER_VERSION,
        )
        imported_assessment = article.get("assessment") or {}
        final_patch = {
            key: imported_assessment[key]
            for key in ("finalCategory", "finalEventType", "finalPriority", "finalTone")
            if key in imported_assessment
        }
        if final_patch:
            article_repo.patch_final_assessment(connection, article_id, final_patch)
        briefing_repo.set_article_state(
            connection,
            briefing["id"],
            article_id,
            selected=bool(article.get("included")),
            starred=bool(article.get("starred")),
            note=article.get("note") or None,
            dismissed=bool(article.get("dismissed")),
            sort_order=article.get("sortOrder") if article.get("sortOrder") is not None else index,
        )
        if article.get("id"):
            article_id_map[article["id"]] = article_id

    issues_imported = issue_repo.import_snapshots(
        connection,
        report_date,
        payload.get("issues") or [],
        article_id_map,
    )
    ai_runs_imported = ai_run_repo.import_runs(
        connection,
        briefing["id"],
        payload.get("aiRuns") or [],
        article_id_map,
    )

    refreshed = briefing_repo.get_by_id(connection, briefing["id"])
    return {
        "reportDate": report_date,
        "articlesImported": len(imported_articles),
        "issuesImported": issues_imported,
        "aiRunsImported": ai_runs_imported,
        "revision": refreshed["revision"],
    }
