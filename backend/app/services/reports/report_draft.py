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


# 외부 분석(평문) 경로에서 생성하는 keyIssue의 제목 마커.
# 렌더러가 이 제목으로 ③(기타 참고 동향)/④(정부부처 동향) 라우팅을 구분한다.
REFERENCE_ISSUE_TITLE = "기타 동향"
GOVERNMENT_ISSUE_TITLE = "정부부처 동향"


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
                "governmentPressRelease": bool(article.get("governmentPressRelease")),
                "governmentProviders": article.get("governmentProviders") or [],
                "governmentSources": article.get("governmentSources") or [],
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
        "government": re.compile(
            r"(?im)^\s*(?:(?:③|④|3[.)]?|4[.)]?)\s*)?정부\s*부처\s*동향\s*$"
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
        # 과거 편집본은 전체 평문을 managementMessage에 다시 감싸 저장하면서 같은
        # 섹션이 중첩될 수 있었다. 이 경우 화면 상단에서 사용자가 수정한 첫 섹션을
        # 뒤쪽의 오래된 복제본으로 덮어쓰지 않는다.
        if value and section not in sections:
            sections[section] = value

    core = sections.get("core") or normalized
    implication = sections.get("implication") or ""
    references = sections.get("reference") or ""
    government = sections.get("government") or ""
    management = sections.get("management") or ""
    if references.rstrip(" .") in {"별도 기타 동향 없음", "별도 참고 동향 없음"}:
        references = ""
    if government.rstrip(" .") in {"별도 정부부처 동향 없음", "정부부처 동향 없음"}:
        government = ""
    if management.rstrip(" .") == "직접적인 경영 현안은 제한적입니다":
        management = ""

    def _reference_issue(title: str, summary: str) -> dict[str, Any]:
        return {
            "title": title,
            "urgency": "reference",
            "summary": summary,
            "managementImpact": "",
            "articleIds": evidence_ids,
            "evidenceQuotes": [
                {"articleId": article_id, "fact": summary}
                for article_id in evidence_ids
            ],
            "certainty": "reported",
            "electricalCauseStatus": "not_applicable",
            "kescoJurisdiction": "MONITORING",
            "jurisdictionReason": "외부 분석 텍스트로 입력됨",
            "excludedElements": [],
            "recommendation": "",
            "actionLevel": "policy_monitoring",
        }

    key_issues: list[dict[str, Any]] = []
    if references:
        key_issues.append(_reference_issue(REFERENCE_ISSUE_TITLE, references))
    if government:
        key_issues.append(_reference_issue(GOVERNMENT_ISSUE_TITLE, government))
    return {
        "managementMessage": {"text": core, "articleIds": evidence_ids},
        "situationSummary": {
            "text": implication,
            "articleIds": evidence_ids if implication else [],
        },
        "keyIssues": key_issues,
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


def normalize_plain_text_content(content: dict[str, Any]) -> dict[str, Any]:
    """단일 필드에 저장된 과거 평문 편집본을 섹션별 구조로 읽기 전용 정규화한다."""
    management = content.get("managementMessage")
    if not isinstance(management, dict):
        return content
    management_text = str(management.get("text") or "")
    evidence_ids = list(management.get("articleIds") or [])
    has_separate_sections = bool(
        str((content.get("situationSummary") or {}).get("text") or "")
        or content.get("keyIssues")
        or content.get("decisionPoints")
        or content.get("actionItems")
        or str((content.get("riskOutlook") or {}).get("text") or "")
    )
    if not management_text or has_separate_sections:
        return content
    parsed = content_from_plain_text(management_text, evidence_ids)
    if parsed["managementMessage"]["text"] == management_text:
        return content
    return {**content, **parsed}
