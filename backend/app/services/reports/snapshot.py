from __future__ import annotations

import sqlite3
from typing import Any

from backend.app.repositories import ai_run_repository as ai_run_repo
from backend.app.repositories import article_repository as article_repo
from backend.app.repositories import issue_repository as issue_repo
from backend.app.repositories import report_draft_repository as report_draft_repo
from backend.app.repositories import weather_repository as weather_repo
from backend.app.services.ai.analyzer import build_evidence_input, input_signature
from backend.app.services.ai.ollama_client import DEFAULT_CONTEXT_LENGTH
from backend.app.services.reports.report_draft import build_exchange_context
from backend.app.services.weather.ai_context import build_weather_ai_context

SNAPSHOT_SCHEMA_VERSION = 1


def _briefing_snapshot(briefing: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": briefing["id"],
        "reportDate": briefing["report_date"],
        "preparedBy": briefing["prepared_by"],
        "status": briefing["status"],
        "situationSummary": briefing["situation_summary"],
        "actionNote": briefing["action_note"],
        "summaryMode": briefing["summary_mode"],
        "aiModel": briefing["ai_model"],
        "aiPromptVersion": briefing["ai_prompt_version"],
        "aiGeneratedAt": briefing["ai_generated_at"],
        "aiInputSignature": briefing["ai_input_signature"],
        "revision": briefing["revision"],
    }


def _evidence_snapshot(
    ai_run: dict[str, Any] | None, articles_by_id: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    if ai_run is None:
        return {}
    request_articles = {
        item.get("id"): item for item in (ai_run.get("request") or {}).get("articles", [])
    }
    result: dict[str, dict[str, Any]] = {}
    for evidence_id, article_id in (ai_run.get("evidence") or {}).items():
        article = articles_by_id.get(article_id)
        if article is None:
            source = request_articles.get(evidence_id) or {}
            article = {
                "id": article_id,
                "title": source.get("title") or "근거 기사",
                "source": source.get("source") or "",
                "pubDate": source.get("publishedAt"),
                "description": source.get("content") or "",
                "url": "",
                "note": source.get("editorNote") or "",
            }
        result[evidence_id] = {"articleId": article_id, "article": article}
    return result


def build_snapshot(
    connection: sqlite3.Connection,
    briefing: sqlite3.Row,
    *,
    version: int | None,
    finalized_at: str | None,
) -> dict[str, Any]:
    all_articles = article_repo.list_candidates(
        connection, briefing["report_date"], include_dismissed=True
    )
    selected_articles = sorted(
        (item for item in all_articles if item.get("included")),
        key=lambda item: (item.get("sortOrder") is None, item.get("sortOrder") or 0, item["id"]),
    )
    articles_by_id = {item["id"]: item for item in all_articles}
    selected_ids = {item["id"] for item in selected_articles}
    issues = [
        item
        for item in issue_repo.list_for_report_date(connection, briefing["report_date"])
        if selected_ids.intersection(item.get("articleIds") or [])
    ]
    issue_state_rows = connection.execute(
        "SELECT * FROM briefing_issues WHERE briefing_id = ?", (briefing["id"],)
    ).fetchall()
    issue_states = {
        row["issue_id"]: {
            "selected": bool(row["selected"]),
            "starred": bool(row["starred"]),
            "note": row["note"] or "",
            "sortOrder": row["sort_order"],
        }
        for row in issue_state_rows
    }
    issues = [
        {**item, "briefingState": issue_states.get(item["id"])}
        for item in issues
        if item["id"] not in issue_states or issue_states[item["id"]]["selected"]
    ]
    success = ai_run_repo.latest_success(connection, briefing["id"])
    ai_run = ai_run_repo.serialize(success)
    if ai_run is not None:
        issue_ids_by_article: dict[str, list[str]] = {}
        for issue in issue_repo.list_for_report_date(connection, briefing["report_date"]):
            for article_id in issue.get("articleIds") or []:
                issue_ids_by_article.setdefault(article_id, []).append(issue["id"])
        current_input, _ = build_evidence_input(all_articles, issue_ids_by_article)
        run_context_length = (ai_run.get("request") or {}).get(
            "contextLength", DEFAULT_CONTEXT_LENGTH
        )
        weather_context, _, _ = build_weather_ai_context(
            weather_repo.snapshot_for_briefing(connection, briefing["id"])
        )
        ai_run["stale"] = (
            input_signature(
                ai_run["model"], current_input, run_context_length, weather_context
            )
            != ai_run["inputSignature"]
        )
    report_draft_row = report_draft_repo.get(connection, briefing["id"])
    exchange_context = build_exchange_context(connection, briefing["report_date"])
    report_draft = report_draft_repo.serialize(
        report_draft_row,
        stale=bool(
            report_draft_row is not None
            and report_draft_row["input_signature"] != exchange_context.signature
        ),
    )
    evidence = _evidence_snapshot(ai_run, articles_by_id)
    if report_draft is not None:
        evidence = {
            evidence_id: {
                "articleId": article_id,
                "article": articles_by_id.get(article_id)
                or {"id": article_id, "title": "근거 기사", "source": ""},
            }
            for evidence_id, article_id in report_draft["evidence"].items()
        }
    snapshot = {
        "snapshotSchemaVersion": SNAPSHOT_SCHEMA_VERSION,
        "reportDate": briefing["report_date"],
        "version": version,
        "sourceRevision": briefing["revision"],
        "finalizedAt": finalized_at,
        "briefing": _briefing_snapshot(briefing),
        "articles": selected_articles,
        "issues": issues,
        "aiRun": ai_run,
        "reportDraft": report_draft,
        "evidence": evidence,
        "weather": weather_repo.snapshot_for_briefing(connection, briefing["id"]),
    }
    if version is not None:
        snapshot["briefing"]["status"] = "final"
    return snapshot
