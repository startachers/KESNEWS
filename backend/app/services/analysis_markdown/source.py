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
    issues = issue_repo.list_for_report_date(connection, report_date)
    missing: list[dict[str, Any]] = []
    for issue in issues:
        members = set(issue.get("articleIds") or [])
        if not members.intersection(originally_selected):
            continue
        representative_id = issue.get("representativeArticleId")
        if not representative_id or representative_id not in by_id:
            if issue.get("effectivePriority") == "required":
                selected_member = next(
                    (article for article in exchange.articles if article["id"] in members),
                    None,
                )
                issue_title = issue.get("effectiveTitle") or issue.get("autoTitle") or ""
                missing.append({
                    "issueId": issue["id"],
                    "issueTitle": issue_title,
                    "articleId": selected_member["id"] if selected_member else "",
                    "title": (
                        selected_member.get("title") if selected_member else issue_title
                    ) or issue_title,
                    "source": selected_member.get("source") if selected_member else "",
                    "url": selected_member.get("url") if selected_member else "",
                    "reason": "representative_evidence_missing",
                    "errors": [{
                        "code": "REQUIRED_ARTICLE_EVIDENCE_MISSING",
                        "status": "representative_evidence_missing",
                        "message": "필수 보고 이슈의 대표 근거 기사를 확보하지 못했습니다.",
                    }],
                    "availableActions": ["관련기사 선택", "본문 다시 추출", "원문 확인"],
                })

    chosen: list[dict[str, Any]] = []
    for article in exchange.articles:
        memberships = [
            issue for issue in issues if article["id"] in set(issue.get("articleIds") or [])
        ]
        representative_issue = next(
            (
                issue for issue in memberships
                if issue.get("representativeArticleId") == article["id"]
            ),
            None,
        )
        supplemental_issue = next(
            (
                issue for issue in memberships
                if article["id"] in set(issue.get("manualSupplementalArticleIds") or [])
            ),
            None,
        )
        primary_issue = representative_issue or supplemental_issue or (memberships[0] if memberships else None)
        if representative_issue:
            evidence_role = "representative"
            selection_method = (
                "manual" if representative_issue.get("manualRepresentative") else "automatic"
            )
        elif supplemental_issue:
            evidence_role = "supplemental"
            selection_method = "manual"
        else:
            evidence_role = "briefing_selected"
            selection_method = "briefing"
        chosen.append({
            **article,
            "issueId": primary_issue["id"] if primary_issue else None,
            "issueTitle": (
                primary_issue.get("effectiveTitle") or primary_issue.get("autoTitle") or ""
                if primary_issue else ""
            ),
            "evidenceRole": evidence_role,
            "evidenceSelectionMethod": selection_method,
        })
    evidence = {f"A{index:02d}": item["id"] for index, item in enumerate(chosen, start=1)}
    raw = json.dumps(
        {
            "baseExchangeSignature": exchange.signature,
            "evidence": [{
                "id": item["id"], "issueId": item.get("issueId"),
                "role": item.get("evidenceRole"), "selection": item.get("evidenceSelectionMethod"),
                "bodyText": item.get("bodyText") or "", "description": item.get("description") or "",
                "note": item.get("note") or "", "starred": bool(item.get("starred")),
                "governmentPressRelease": bool(item.get("governmentPressRelease")),
                "governmentProviders": item.get("governmentProviders") or [],
                "governmentSources": item.get("governmentSources") or [],
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
