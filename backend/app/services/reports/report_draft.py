from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from backend.app.repositories import article_repository as article_repo
from backend.app.repositories import issue_repository as issue_repo
from backend.app.services.ai.analyzer import select_articles
from backend.app.services.ai.schemas import AnalysisResult, validate_evidence


class ReportDraftInvalid(ValueError):
    pass


class ReportDraftStale(ValueError):
    pass


@dataclass(frozen=True)
class ExchangeContext:
    articles: list[dict[str, Any]]
    evidence: dict[str, str]
    signature: str
    issues_by_article: dict[str, list[dict[str, Any]]]


def build_exchange_context(connection: sqlite3.Connection, report_date: str) -> ExchangeContext:
    candidates = article_repo.list_candidates(connection, report_date, include_dismissed=False)
    selected = select_articles(candidates, limit=max(1, len(candidates)))
    evidence = {f"A{index:02d}": item["id"] for index, item in enumerate(selected, start=1)}
    issues_by_article: dict[str, list[dict[str, Any]]] = {}
    for issue in issue_repo.list_for_report_date(connection, report_date):
        issue_data = {
            "id": issue["id"],
            "title": issue.get("effectiveTitle") or issue.get("autoTitle") or "",
            "status": issue.get("effectiveStatus") or "",
            "reviewStars": issue.get("effectiveReviewStars"),
            "selected": bool(issue.get("selected")),
            "starred": bool(issue.get("starred")),
            "note": issue.get("note") or "",
        }
        for article_id in issue.get("articleIds") or []:
            issues_by_article.setdefault(article_id, []).append(issue_data)
    signature_rows = []
    for evidence_id, article in zip(evidence, selected, strict=True):
        signature_rows.append(
            {
                "evidenceId": evidence_id,
                "id": article["id"],
                "title": article.get("title") or "",
                "source": article.get("source") or "",
                "publishedAt": article.get("pubDate"),
                "bodyText": article.get("bodyText") or "",
                "description": article.get("description") or "",
                "bodyStatus": article.get("bodyStatus") or "missing",
                "bodyError": article.get("bodyError") or "",
                "starred": bool(article.get("starred")),
                "topIssue": bool(article.get("topIssue")),
                "note": article.get("note") or "",
                "category": article.get("category"),
                "priority": article.get("priority"),
                "risk": article.get("risk"),
                "sentiment": article.get("sentiment"),
                "eventType": article.get("eventType"),
                "matchedKeywords": article.get("matchedKeywords") or [],
                "issues": issues_by_article.get(article["id"], []),
            }
        )
    raw = json.dumps(signature_rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    signature = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return ExchangeContext(selected, evidence, signature, issues_by_article)


def validate_content(
    content: dict[str, Any], evidence: dict[str, str]
) -> dict[str, Any]:
    try:
        result = AnalysisResult.model_validate(content)
        validate_evidence(result, set(evidence))
    except (ValidationError, ValueError) as exc:
        raise ReportDraftInvalid(str(exc)) from exc
    return result.model_dump()


def normalize_external_payload(payload: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    signature = payload.get("inputSignature")
    content = payload.get("analysis") if isinstance(payload.get("analysis"), dict) else payload
    if content is payload:
        content = {
            key: value
            for key, value in payload.items()
            if key not in {"reportDate", "inputSignature", "sourceLabel"}
        }
    if not isinstance(content, dict):
        raise ReportDraftInvalid("analysis 객체가 필요합니다.")
    return str(signature) if signature else None, content


def content_from_plain_text(text: str, evidence_ids: list[str]) -> dict[str, Any]:
    normalized = str(text or "").strip()
    if not normalized:
        raise ReportDraftInvalid("붙여넣은 분석 텍스트가 없습니다.")
    headings = {
        "core": re.compile(
            r"(?im)^\s*(?:(?:①|1[.)]?)\s*)?(?:오늘\s*한줄|오늘의\s*핵심|언론\s*동향\s*시사점)\s*$"
        ),
        "implication": re.compile(
            r"(?im)^\s*(?:(?:②|2[.)]?)\s*)?(?:경영\s*시사점|언론\s*동향\s*분석)\s*$"
        ),
        "management": re.compile(
            r"(?im)^\s*(?:(?:③|3[.)]?)\s*)?경영\s*참고\s*사항\s*$"
        ),
        "reference": re.compile(
            r"(?im)^\s*(?:(?:③|④|3[.)]?|4[.)]?)\s*)?(?:기타|참고)\s*동향\s*$"
        ),
    }
    matches = sorted(
        (
            (match.start(), match.end(), section)
            for section, pattern in headings.items()
            for match in pattern.finditer(normalized)
        ),
        key=lambda item: item[0],
    )
    sections: dict[str, str] = {}
    for index, (_, end, section) in enumerate(matches):
        next_start = matches[index + 1][0] if index + 1 < len(matches) else len(normalized)
        value = normalized[end:next_start].strip()
        if value:
            sections[section] = value

    core = sections.get("core") or normalized
    implication = sections.get("implication") or ""
    references = sections.get("reference") or ""
    management = sections.get("management") or ""
    if references.rstrip(" .") in {"별도 기타 동향 없음", "별도 참고 동향 없음"}:
        references = ""
    if management.rstrip(" .") == "직접적인 경영 현안은 제한적입니다":
        management = ""
    return {
        "managementMessage": {"text": core, "articleIds": evidence_ids},
        "situationSummary": {
            "text": implication,
            "articleIds": evidence_ids if implication else [],
        },
        "keyIssues": (
            [{
                "title": "기타 동향",
                "urgency": "reference",
                "summary": references,
                "managementImpact": "",
                "articleIds": evidence_ids,
                "evidenceQuotes": [
                    {"articleId": article_id, "fact": references}
                    for article_id in evidence_ids
                ],
                "certainty": "reported",
                "electricalCauseStatus": "not_applicable",
                "kescoJurisdiction": "MONITORING",
                "jurisdictionReason": "외부 분석의 기타 동향으로 입력됨",
                "excludedElements": [],
                "recommendation": "",
                "actionLevel": "policy_monitoring",
            }]
            if references
            else []
        ),
        "decisionPoints": [],
        "actionItems": (
            [{
                "priority": "review",
                "action": management,
                "articleIds": evidence_ids,
                "kescoJurisdiction": "DIRECT",
                "actionLevel": "internal_review",
                "evidence": "외부 분석 텍스트와 현재 선정 기사",
                "uncertainty": "reported",
                "ownerType": "KESCO",
            }]
            if management
            else []
        ),
        "riskOutlook": {"text": "", "articleIds": [], "isInference": True},
        "limitations": [],
        "confidence": "medium",
    }
