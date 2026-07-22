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
        # 담당자가 확정한 기존 그룹을 최우선한다. 그룹이 없을 때는 날짜와 핵심 명사
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


def search_related_candidates(
    original: dict,
    *,
    lookback_hours: int = 2160,
    limit: int = 10,
) -> list[dict]:
    """사용자가 요청한 단건 보강 검색이다.

    일반 수집의 검색그룹 관련도, 제외어, 당일 기간 제한과 신뢰 언론사 허용목록은 적용하지
    않는다. Google RSS가 제공한 원 발행사 도메인은 반드시 확인해 출처 미상만 제외한다.
    """
    query_variants = related_query_variants(original)
    if not query_variants:
        return []
    collected: list[dict] = []
    failures: list[Exception] = []
    for query in query_variants:
        try:
            collected.extend(
                {**item, "_relatedQuery": query}
                for item in fetch_google_rss(query, lookback_hours, 50)
            )
        except Exception as exc:  # 한 조합 실패가 다른 조합 결과를 버리지 않게 한다.
            failures.append(exc)
    if not collected and failures:
        raise failures[0]
    return rank_related_candidates(original, collected, limit=limit)


def related_query_variants(original: dict) -> list[str]:
    """긴 제목 하나 대신 사건 단서를 보존한 짧은 검색식 여러 개를 만든다."""
    ordered_terms = list(dict.fromkeys(
        token for token in re.findall(r"[가-힣A-Za-z0-9]{2,}", original.get("title") or "")
        if token.lower() not in _STOP
    ))
    if not ordered_terms:
        return []
    candidates: list[list[str]] = []
    if len(ordered_terms) <= 3:
        candidates.append(ordered_terms)
    else:
        candidates.extend([
            ordered_terms[:3],
            ordered_terms[-3:],
            ordered_terms[:2],
            ordered_terms[1:4],
            [ordered_terms[0], ordered_terms[-1]],
        ])
    return list(dict.fromkeys(" ".join(parts) for parts in candidates if parts))


def rank_related_candidates(original: dict, items: list[dict], *, limit: int = 10) -> list[dict]:
    original_terms = _terms(original.get("title") or "")
    media_config = load_trusted_media_config()
    original_url = str(original.get("canonicalUrl") or original.get("url") or "")
    scored: list[tuple[int, float, float, dict]] = []
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    for item in items:
        decision = identify_trusted_publisher(item, config=media_config)
        if not decision.hostname:
            continue
        title = str(item.get("title") or "").strip()
        candidate_terms = _terms(title)
        context_terms = _terms(f"{title} {item.get('description') or ''}")
        shared = original_terms & context_terms
        shared_count = len(shared)
        title_shared_count = len(original_terms & candidate_terms)
        similarity = shared_count / max(1, len(original_terms | context_terms))
        # 짧은 다중 검색식 자체가 사건 단서를 보장한다. 결과 후처리는 고유 단서 1개까지 허용한다.
        if not shared:
            continue
        url = str(item.get("url") or "")
        normalized_title = " ".join(title.lower().split())
        if not url or url == original_url or normalized_title in seen_titles or url in seen_urls:
            continue
        seen_urls.add(url)
        seen_titles.add(normalized_title)
        published = _date(item.get("pubDate"))
        published_score = published.timestamp() if published else 0.0
        scored.append((title_shared_count * 2 + shared_count, similarity, published_score, {
            **item,
            "id": item.get("id") or "",
            "publisherId": decision.publisher_id or f"related-search:{decision.hostname}",
            "publisherAllowed": True,
            "relatedSearchPolicy": "relaxed_topic_filters_v1",
            "relatedSearchPublisherScope": "trusted" if decision.allowed else "domain_identified",
        }))
    scored.sort(key=lambda entry: (entry[0], entry[1], entry[2]), reverse=True)
    return [entry[3] for entry in scored[: max(1, min(50, limit))]]
