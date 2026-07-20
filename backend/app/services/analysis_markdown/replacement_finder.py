from __future__ import annotations

import re
from datetime import datetime

from backend.app.services.collection.google_news import fetch_google_rss
from backend.app.services.media import identify_trusted_publisher, load_trusted_media_config

_STOP = {"관련", "대한", "통해", "위한", "기사", "정부", "오늘", "이번", "대신", "과제"}


def _terms(title: str) -> set[str]:
    return {
        token for token in re.findall(r"[가-힣A-Za-z0-9]{2,}", title.lower())
        if token not in _STOP
    }


def _date(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat((value or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def find_replacement(
    original: dict,
    candidates: list[dict],
    *,
    issue_ids_by_article: dict[str, set[str]],
) -> dict | None:
    original_terms = _terms(original.get("title") or "")
    original_issues = issue_ids_by_article.get(original["id"], set())
    scored: list[tuple[float, dict]] = []
    for candidate in candidates:
        if candidate["id"] == original["id"] or not candidate.get("publisherAllowed"):
            continue
        if not candidate.get("analysisEligible"):
            continue
        shared_issues = original_issues & issue_ids_by_article.get(candidate["id"], set())
        candidate_terms = _terms(candidate.get("title") or "")
        shared = original_terms & candidate_terms
        union = original_terms | candidate_terms
        similarity = len(shared) / max(1, len(union))
        first_date, second_date = _date(original.get("pubDate")), _date(candidate.get("pubDate"))
        close_date = bool(first_date and second_date and abs((first_date - second_date).total_seconds()) <= 3 * 86400)
        # 담당자가 확정한 기존 군집을 최우선한다. 군집이 없을 때는 날짜와 핵심 명사
        # 3개 이상 및 높은 제목 유사도를 모두 요구해 다른 사건 오인을 피한다.
        if shared_issues:
            score = 2.0 + similarity
        elif close_date and len(shared) >= 3 and similarity >= 0.45:
            score = similarity
        else:
            continue
        scored.append((score, candidate))
    return max(scored, key=lambda item: item[0])[1] if scored else None


def search_trusted_candidates(original: dict, *, lookback_hours: int = 168) -> list[dict]:
    """기존 Google 뉴스 RSS 검색기를 재사용하며 허용목록 매체만 반환한다."""
    query = " ".join(sorted(_terms(original.get("title") or ""))[:6])
    if not query:
        return []
    media_config = load_trusted_media_config()
    results = []
    for item in fetch_google_rss(query, lookback_hours, 20):
        decision = identify_trusted_publisher(item, config=media_config)
        if not decision.allowed:
            continue
        results.append({
            **item,
            "id": item.get("id") or "",
            "publisherId": decision.publisher_id,
            "publisherAllowed": True,
            "bodyText": "",
            "bodyStatus": "missing",
            "priority": original.get("priority"),
            "category": original.get("category"),
            "eventType": original.get("eventType"),
            "risk": original.get("risk"),
            "sentiment": original.get("sentiment"),
            "relevanceScore": original.get("relevanceScore"),
            "severityScore": original.get("severityScore"),
            "priorityScore": original.get("priorityScore"),
            "note": original.get("note") or "",
            "starred": original.get("starred"),
            "topIssue": original.get("topIssue"),
        })
    return results
