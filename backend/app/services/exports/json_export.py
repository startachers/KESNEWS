from __future__ import annotations

import sqlite3
from copy import deepcopy
from datetime import date, timedelta
from typing import Any

from backend.app.core.clock import now_iso
from backend.app.repositories import article_repository as article_repo
from backend.app.repositories import ai_run_repository as ai_run_repo
from backend.app.repositories import briefing_repository as briefing_repo
from backend.app.repositories import briefing_version_repository as version_repo
from backend.app.repositories import issue_repository as issue_repo
from backend.app.repositories import press_release_repository as press_release_repo
from backend.app.repositories import report_draft_repository as report_draft_repo
from backend.app.repositories import weather_repository as weather_repo
from backend.app.repositories.database import backup_database
from backend.app.services.classification.service import CLASSIFIER_VERSION, classify_article
from backend.app.services.ids import make_id
from backend.app.services.normalization.dates import since_bound_iso
from backend.app.services.reports.renderer import render_report
from backend.app.services.reports.report_draft import build_exchange_context, validate_content
from backend.app.services.reports.storage import write_report

SCHEMA_VERSION = 12
SUPPORTED_SCHEMA_VERSIONS = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12}

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
    issues = issue_repo.list_for_report_date(connection, report_date)
    issue_states = briefing_repo.list_issue_states(connection, report_date)
    for issue in issues:
        state = issue_states.get(issue["id"], {})
        issue.update(state)
        issue["autoDirectCoverage"] = bool(issue["directMention"])
        override = state.get("editorDirectCoverage")
        issue["directCoverage"] = (
            override if override is not None else issue["autoDirectCoverage"]
        )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "reportDate": report_date,
        "exportedAt": now_iso(),
        "briefing": {key: briefing[column] for key, column in _BRIEFING_EXPORT_FIELDS.items()},
        "articles": articles,
        "issues": issues,
        "aiRuns": [
            ai_run_repo.serialize(row)
            for row in ai_run_repo.list_for_briefing(connection, briefing["id"])
        ],
        "reportDraft": report_draft_repo.serialize(
            report_draft_repo.get(connection, briefing["id"])
        ),
        "weather": weather_repo.export_for_briefing(connection, briefing["id"]),
        "briefingVersions": [
            version_repo.serialize(row)
            for row in reversed(version_repo.list_versions(connection, briefing["id"]))
        ],
    }


def build_version_export(row: sqlite3.Row, report_date: str) -> dict[str, Any]:
    serialized = version_repo.serialize(row)
    snapshot = serialized["snapshot"]
    ai_run = snapshot.get("aiRun")
    return {
        "schemaVersion": SCHEMA_VERSION,
        "reportDate": report_date,
        "exportedAt": now_iso(),
        "briefing": snapshot.get("briefing") or {},
        "articles": snapshot.get("articles") or [],
        "issues": snapshot.get("issues") or [],
        "aiRuns": [ai_run] if ai_run else [],
        "reportDraft": snapshot.get("reportDraft"),
        "weather": snapshot.get("weather"),
        "briefingVersions": [serialized],
    }


def _remap_snapshot(
    snapshot: dict[str, Any],
    report_date: str,
    briefing_id: str,
    article_id_map: dict[str, str],
) -> dict[str, Any]:
    result = deepcopy(snapshot)
    result["reportDate"] = report_date
    briefing = result.get("briefing") or {}
    briefing["id"] = briefing_id
    briefing["reportDate"] = report_date
    for article in result.get("articles") or []:
        if article.get("id") in article_id_map:
            article["id"] = article_id_map[article["id"]]
    for issue in result.get("issues") or []:
        for field in ("representativeArticleId",):
            if issue.get(field) in article_id_map:
                issue[field] = article_id_map[issue[field]]
        for field in ("articleIds", "autoArticleIds"):
            issue[field] = [article_id_map.get(item, item) for item in issue.get(field) or []]
        for item in issue.get("membershipOverrides") or []:
            article_id = item.get("article_id")
            if article_id in article_id_map:
                item["article_id"] = article_id_map[article_id]
    ai_run = result.get("aiRun") or {}
    ai_run["evidence"] = {
        key: article_id_map.get(article_id, article_id)
        for key, article_id in (ai_run.get("evidence") or {}).items()
    }
    report_draft = result.get("reportDraft") or {}
    report_draft["evidence"] = {
        key: article_id_map.get(article_id, article_id)
        for key, article_id in (report_draft.get("evidence") or {}).items()
    }
    for item in (result.get("evidence") or {}).values():
        old_id = item.get("articleId")
        new_id = article_id_map.get(old_id, old_id)
        item["articleId"] = new_id
        if isinstance(item.get("article"), dict):
            item["article"]["id"] = new_id
    weather = result.get("weather") or {}
    weather_context = weather.get("context") or {}
    source_period_from = (weather_context.get("period") or {}).get("from")
    if weather_context:
        weather_context["reportDate"] = report_date
        weather_context["period"] = {
            "from": report_date,
            "to": (date.fromisoformat(report_date) + timedelta(days=6)).isoformat(),
        }
        if source_period_from:
            for day in weather_context.get("days") or []:
                if not day.get("date"):
                    continue
                offset = (
                    date.fromisoformat(day["date"])
                    - date.fromisoformat(source_period_from)
                ).days
                day["date"] = (
                    date.fromisoformat(report_date) + timedelta(days=offset)
                ).isoformat()
    return result


def _validate_version_conflicts(
    connection: sqlite3.Connection,
    existing: sqlite3.Row | None,
    versions: list[dict[str, Any]],
) -> None:
    if existing is None:
        return
    for item in versions:
        version = int(item.get("version") or 0)
        current = version_repo.get_version(connection, existing["id"], version)
        if current is None:
            continue
        if version_repo.serialize(current).get("snapshot") != item.get("snapshot"):
            raise ImportConflict(
                {"version": version, "reason": "immutable_final_snapshot_differs"}
            )


def import_export(
    connection: sqlite3.Connection, report_date: str, payload: dict[str, Any], mode: str | None
) -> dict[str, Any]:
    schema_version = payload.get("schemaVersion")
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise SchemaUnsupported()

    existing = briefing_repo.get_by_date(connection, report_date)
    imported_versions = payload.get("briefingVersions") or []
    _validate_version_conflicts(connection, existing, imported_versions)
    if existing is not None and mode != "replace":
        raise ImportConflict({"existingRevision": existing["revision"]})

    if existing is not None and mode == "replace":
        backup_database()
        connection.execute(
            "DELETE FROM briefing_weather_signals WHERE briefing_id = ?", (existing["id"],)
        )
        connection.execute(
            "DELETE FROM briefing_weather WHERE briefing_id = ?", (existing["id"],)
        )
        connection.execute(
            "DELETE FROM briefing_report_drafts WHERE briefing_id = ?", (existing["id"],)
        )
        connection.execute("DELETE FROM ai_runs WHERE briefing_id = ?", (existing["id"],))
        connection.execute("DELETE FROM briefing_articles WHERE briefing_id = ?", (existing["id"],))
        if existing["status"] == "final":
            connection.execute(
                "UPDATE briefings SET status = 'draft', finalized_at = NULL WHERE id = ?",
                (existing["id"],),
            )

    expected_revision = existing["revision"] if existing is not None else 0
    briefing_patch = dict(payload.get("briefing") or {})
    desired_status = briefing_patch.pop("status", "draft")
    if desired_status in {"draft", "reviewed"}:
        briefing_patch["status"] = desired_status
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
        matched_query_ids = [
            str(query_id)
            for query_id in (article.get("matchedQueryIds") or [])
            if str(query_id).strip()
        ]
        for query_id in matched_query_ids:
            article_repo.insert_observation(
                connection,
                article_id=article_id,
                collection_run_provider_id=None,
                provider="import",
                provider_item_key=None,
                query_group_id=query_id,
                raw_url=article.get("url"),
                raw_title=article.get("title"),
                raw_source=article.get("source"),
                raw_published_at=article.get("pubDate"),
                raw_description=article.get("description"),
                raw_payload_json=None,
                dedup_method="imported_observation",
                dedup_score=None,
            )
        imported_assessment = article.get("assessment") or {}
        final_patch = {
            key: imported_assessment[key]
            for key in ("finalCategory", "finalEventType", "finalPriority", "finalTone")
            if key in imported_assessment
        }
        if final_patch:
            article_repo.patch_final_assessment(connection, article_id, final_patch)
        if any(
            key in article
            for key in ("bodyText", "bodyStatus", "bodyFetchedAt", "bodyError")
        ):
            article_repo.update_article_body(
                connection,
                article_id,
                body_text=article.get("bodyText") or "",
                body_status=article.get("bodyStatus") or "missing",
                body_error=article.get("bodyError") or "",
                fetched_at=article.get("bodyFetchedAt"),
            )
        if article.get("origin"):
            press_release_repo.import_origin(
                connection,
                article_id,
                article["origin"],
            )
        briefing_repo.set_article_state(
            connection,
            briefing["id"],
            article_id,
            selected=bool(article.get("included")),
            starred=bool(article.get("starred")),
            top_issue=bool(article.get("topIssue")),
            note=article.get("note") or None,
            dismissed=bool(article.get("dismissed")),
            sort_order=article.get("sortOrder") if article.get("sortOrder") is not None else index,
            direct_coverage_override=article.get("editorDirectCoverage"),
        )
        if article.get("id"):
            article_id_map[article["id"]] = article_id

    issues_imported = issue_repo.import_snapshots(
        connection,
        report_date,
        payload.get("issues") or [],
        article_id_map,
    )
    briefing_repo.normalize_direct_coverage(connection, report_date)
    ai_runs_imported = ai_run_repo.import_runs(
        connection,
        briefing["id"],
        payload.get("aiRuns") or [],
        article_id_map,
    )
    imported_report_draft = payload.get("reportDraft")
    if imported_report_draft:
        context = build_exchange_context(connection, report_date)
        content = validate_content(imported_report_draft.get("content") or {}, context.evidence)
        report_draft_repo.upsert(
            connection,
            briefing_id=briefing["id"],
            source_type=(
                imported_report_draft.get("sourceType")
                if imported_report_draft.get("sourceType") in {"gemma", "external", "manual"}
                else "manual"
            ),
            source_label=imported_report_draft.get("sourceLabel") or "",
            content=content,
            evidence=context.evidence,
            input_signature=context.signature,
            based_on_ai_run_id=None,
        )

    imported_weather = payload.get("weather") or {}
    imported_weather_context = imported_weather.get("context") or {}
    imported_weather_attachment = imported_weather.get("attachment") or {}
    if imported_weather_context:
        imported_days = []
        source_period_from = imported_weather_context.get("period", {}).get("from")
        for item in imported_weather_context.get("days") or []:
            copied = dict(item)
            if source_period_from and copied.get("date"):
                offset = (
                    date.fromisoformat(copied["date"])
                    - date.fromisoformat(source_period_from)
                ).days
                copied["date"] = (
                    date.fromisoformat(report_date) + timedelta(days=offset)
                ).isoformat()
            imported_days.append(copied)
        signals = [
            {key: value for key, value in signal.items() if key != "id"}
            for signal in imported_weather_context.get("riskSignals") or []
        ]
        weather_context = weather_repo.create_context(
            connection,
            report_date=report_date,
            period_from=report_date,
            period_to=(date.fromisoformat(report_date) + timedelta(days=6)).isoformat(),
            overall_level=imported_weather_context.get("overallLevel") or "unknown",
            issued_at=imported_weather_context.get("issuedAt"),
            region_config_version=imported_weather_context.get("regionConfigVersion") or "imported",
            risk_rule_version=imported_weather_context.get("riskRuleVersion") or "imported",
            source_status=imported_weather_context.get("sourceStatus") or {},
            days=imported_days,
            alerts=imported_weather_context.get("alerts") or [],
            input_signature=f"import-{report_date}-{imported_weather_context.get('inputSignature') or make_id()}",
            signals=signals,
        )
        imported_by_key = {
            item["signalKey"]: item["id"]
            for item in weather_repo.list_signals(connection, weather_context["id"])
        }
        original_by_id = {
            item["id"]: item["signalKey"]
            for item in imported_weather_context.get("riskSignals") or []
        }
        selected_signals = [
            {
                "id": imported_by_key[original_by_id[item["id"]]],
                "selected": bool(item.get("selected")),
                "editorLevel": item.get("editorLevel"),
                "editorNote": item.get("editorNote") or "",
            }
            for item in imported_weather_attachment.get("signals") or []
            if item.get("id") in original_by_id
            and original_by_id[item["id"]] in imported_by_key
        ]
        briefing = weather_repo.attach_context(
            connection,
            report_date=report_date,
            expected_revision=briefing_repo.get_by_id(connection, briefing["id"])["revision"],
            context_id=weather_context["id"],
            include_in_report=bool(imported_weather_attachment.get("includeInReport")),
            review_status=(
                imported_weather_attachment.get("reviewStatus")
                if imported_weather_attachment.get("reviewStatus") in {"pending", "reviewed"}
                else "pending"
            ),
            selected_signals=selected_signals,
            editor_note=imported_weather_attachment.get("editorNote") or "",
        )

    versions_imported = 0
    for item in imported_versions:
        version = int(item.get("version") or 0)
        if version < 1:
            continue
        current = version_repo.get_version(connection, briefing["id"], version)
        if current is not None:
            continue
        snapshot = _remap_snapshot(
            item.get("snapshot") or {}, report_date, briefing["id"], article_id_map
        )
        html_path = write_report(report_date, version, render_report(snapshot))
        version_repo.import_version(
            connection,
            briefing_id=briefing["id"],
            version=version,
            source_revision=item.get("sourceRevision"),
            snapshot=snapshot,
            finalized_at=item.get("finalizedAt"),
            report_html_path=str(html_path),
        )
        versions_imported += 1

    latest = version_repo.latest_version(connection, briefing["id"])
    if desired_status == "final" and latest is not None:
        connection.execute(
            """
            UPDATE briefings
            SET status = 'final', latest_final_version = ?, finalized_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                latest["version"],
                latest["finalized_at"],
                now_iso(),
                briefing["id"],
            ),
        )

    refreshed = briefing_repo.get_by_id(connection, briefing["id"])
    return {
        "reportDate": report_date,
        "articlesImported": len(imported_articles),
        "issuesImported": issues_imported,
        "aiRunsImported": ai_runs_imported,
        "versionsImported": versions_imported,
        "revision": refreshed["revision"],
    }
