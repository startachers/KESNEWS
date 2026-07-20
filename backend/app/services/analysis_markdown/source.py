from __future__ import annotations

import sqlite3
import hashlib
import json
from dataclasses import dataclass
from typing import Any

from backend.app.repositories import briefing_repository as briefing_repo
from backend.app.repositories import article_repository as article_repo
from backend.app.repositories import issue_repository as issue_repo
from backend.app.repositories import weather_repository as weather_repo
from backend.app.services.analysis_markdown.signature import input_signature
from backend.app.services.reports.report_draft import ExchangeContext, build_exchange_context
from backend.app.services.weather.ai_context import build_weather_ai_context


@dataclass(frozen=True)
class SourceContext:
    briefing: dict[str, Any]
    exchange: ExchangeContext
    weather: dict[str, Any] | None
    signature: str
    missing_required_issues: tuple[dict[str, Any], ...] = ()


def _confirmed_issue_evidence(
    connection: sqlite3.Connection,
    report_date: str,
    exchange: ExchangeContext,
) -> tuple[ExchangeContext, tuple[dict[str, Any], ...]]:
    candidates = article_repo.list_candidates(connection, report_date, include_dismissed=False)
    by_id = {item["id"]: item for item in candidates}
    originally_selected = {item["id"] for item in exchange.articles}
    grouped_ids: set[str] = set()
    chosen: list[dict[str, Any]] = []
    chosen_ids: set[str] = set()
    missing: list[dict[str, Any]] = []
    for issue in issue_repo.list_for_report_date(connection, report_date):
        members = set(issue.get("articleIds") or [])
        grouped_ids.update(members)
        if not members.intersection(originally_selected):
            continue
        representative_id = issue.get("representativeArticleId")
        if not representative_id or representative_id not in by_id:
            if issue.get("effectivePriority") == "required":
                missing.append({
                    "issueId": issue["id"],
                    "title": issue.get("effectiveTitle") or issue.get("autoTitle") or "",
                    "reason": "representative_evidence_missing",
                })
            continue
        evidence_ids = [representative_id, *(issue.get("manualSupplementalArticleIds") or [])]
        excluded = set(issue.get("manualExcludedArticleIds") or [])
        for index, article_id in enumerate(evidence_ids):
            if article_id in chosen_ids or article_id in excluded or article_id not in members or article_id not in by_id:
                continue
            chosen.append({
                **by_id[article_id],
                "issueId": issue["id"],
                "issueTitle": issue.get("effectiveTitle") or issue.get("autoTitle") or "",
                "evidenceRole": "representative" if index == 0 else "supplemental",
                "evidenceSelectionMethod": (
                    "manual" if index > 0 or issue.get("manualRepresentative") else "automatic"
                ),
            })
            chosen_ids.add(article_id)
    for article in exchange.articles:
        if article["id"] in grouped_ids or article["id"] in chosen_ids:
            continue
        chosen.append({
            **article,
            "issueId": None,
            "issueTitle": "",
            "evidenceRole": "representative",
            "evidenceSelectionMethod": "individual",
        })
        chosen_ids.add(article["id"])
    if (
        [item["id"] for item in chosen] == [item["id"] for item in exchange.articles]
        and all(item.get("issueId") is None for item in chosen)
    ):
        return exchange, tuple(missing)
    evidence = {f"A{index:02d}": item["id"] for index, item in enumerate(chosen, start=1)}
    raw = json.dumps(
        {
            "baseExchangeSignature": exchange.signature,
            "evidence": [{
                "id": item["id"], "issueId": item.get("issueId"),
                "role": item.get("evidenceRole"), "selection": item.get("evidenceSelectionMethod"),
                "bodyText": item.get("bodyText") or "", "description": item.get("description") or "",
                "note": item.get("note") or "", "starred": bool(item.get("starred")),
            } for item in chosen],
        },
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    signature = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return ExchangeContext(chosen, evidence, signature, exchange.issues_by_article), tuple(missing)


def weather_context(connection: sqlite3.Connection, briefing_id: str | None) -> dict[str, Any] | None:
    if not briefing_id:
        return None
    attachment = weather_repo.get_attachment(connection, briefing_id)
    if (
        attachment is None
        or not attachment["include_in_report"]
        or attachment["review_status"] != "reviewed"
    ):
        return None
    context, _, _ = build_weather_ai_context(
        weather_repo.snapshot_for_briefing(connection, briefing_id)
    )
    return context


def build_source_context(
    connection: sqlite3.Connection, report_date: str, config: dict[str, Any]
) -> SourceContext | None:
    briefing_row = briefing_repo.get_by_date(connection, report_date)
    if briefing_row is None:
        return None
    briefing = dict(briefing_row)
    exchange = build_exchange_context(connection, report_date)
    exchange, missing_required_issues = _confirmed_issue_evidence(
        connection, report_date, exchange
    )
    weather = weather_context(connection, briefing["id"])
    signature = input_signature(
        {
            "exchangeSignature": exchange.signature,
            "preparedBy": briefing.get("prepared_by") or "",
            "selectedUrlsAndPublishers": [
                {
                    "id": article["id"],
                    "url": article.get("url") or "",
                    "publisherId": article.get("publisherId"),
                    "publisherAllowed": article.get("publisherAllowed"),
                }
                for article in exchange.articles
            ],
            "weather": weather,
            "config": config,
        }
    )
    return SourceContext(briefing, exchange, weather, signature, missing_required_issues)
