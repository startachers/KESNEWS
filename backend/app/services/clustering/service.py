from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from backend.app.services.deduplication.fuzzy import bigram_similarity
from backend.app.services.normalization.dates import date_value

ALGORITHM_VERSION = "event-aware-title-tfidf-v2"
PAIR_THRESHOLD = 0.40
MAJOR_OUTLETS = {
    "연합뉴스", "KBS", "MBC", "SBS", "조선일보", "중앙일보", "동아일보", "한겨레", "경향신문"
}
GENERIC_TERMS = {
    "한국전기안전공사", "전기안전공사", "kesco", "전기", "안전", "관련", "대해", "위한", "실시",
    "밝혔다", "기자", "뉴스", "공사", "정전", "화재", "감전", "점검", "캠페인", "협약", "수사",
    "고발",
}
EVENT_PATTERNS = {
    "outage": re.compile(
        r"정전|전력\s*(?:공급(?:이|을)?\s*)?(?:중단|차단|끊)|전기(?:가|를)?\s*(?:끊|나가)"
    ),
    "fire": re.compile(r"화재|불(?:이)?\s*(?:나|났|붙)|불길"),
    "electric_shock": re.compile(r"감전"),
    "inspection": re.compile(r"안전\s*(?:점검|검사|진단)|특별\s*점검"),
    "campaign": re.compile(r"캠페인|예방\s*홍보"),
    "agreement": re.compile(r"업무\s*협약|협약\s*(?:체결|식)"),
    "investigation": re.compile(r"압수\s*수색|수사|고발"),
}


def input_signature(articles: list[dict[str, Any]]) -> str:
    payload = [
        [
            item["id"],
            item.get("title"),
            item.get("description"),
            item.get("source"),
            item.get("publishedAt"),
            item.get("relevanceScore"),
            item.get("severityScore"),
            item.get("directMention"),
        ]
        for item in sorted(articles, key=lambda article: article["id"])
    ]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()


def _normalized(value: str | None) -> str:
    return re.sub(r"[^0-9a-z가-힣]+", " ", str(value or "").lower()).strip()


def _grams(article: dict[str, Any]) -> Counter[str]:
    title = _normalized(article.get("title"))
    description = _normalized(article.get("description"))[:240]
    text = f"{title} {title} {description}"
    compact = text.replace(" ", "")
    grams = Counter(compact[index : index + 3] for index in range(max(0, len(compact) - 2)))
    for token in text.split():
        if len(token) >= 2 and token not in GENERIC_TERMS:
            grams[f"t:{token}"] += 3
    return grams


def _tfidf_vectors(articles: list[dict[str, Any]]) -> list[dict[str, float]]:
    counters = [_grams(article) for article in articles]
    document_frequency = Counter(gram for counter in counters for gram in counter)
    count = len(counters)
    vectors = []
    for counter in counters:
        vectors.append(
            {
                gram: (1 + math.log(freq)) * (math.log((1 + count) / (1 + document_frequency[gram])) + 1)
                for gram, freq in counter.items()
            }
        )
    return vectors


def _cosine(left: dict[str, float], right: dict[str, float]) -> float:
    common = left.keys() & right.keys()
    numerator = sum(left[key] * right[key] for key in common)
    denominator = math.sqrt(sum(value * value for value in left.values())) * math.sqrt(
        sum(value * value for value in right.values())
    )
    return numerator / denominator if denominator else 0.0


def _distinctive_tokens(article: dict[str, Any]) -> set[str]:
    text = _normalized(f"{article.get('title', '')} {article.get('description', '')}")
    return {
        token for token in text.split()
        if (len(token) >= 3 or token.isdigit()) and token not in GENERIC_TERMS
    }


def _numbers(article: dict[str, Any]) -> set[str]:
    text = f"{article.get('title', '')} {article.get('description', '')}"
    return {value.replace(",", "") for value in re.findall(r"\d[\d,]*(?:\.\d+)?", text)}


def _event_anchors(article: dict[str, Any]) -> set[str]:
    text = _normalized(f"{article.get('title', '')} {article.get('description', '')}")
    return {name for name, pattern in EVENT_PATTERNS.items() if pattern.search(text)}


def pair_score(
    left: dict[str, Any], right: dict[str, Any], left_vector: dict[str, float], right_vector: dict[str, float]
) -> float:
    left_time, right_time = date_value(left.get("publishedAt")), date_value(right.get("publishedAt"))
    hours = abs(left_time - right_time) / 3_600_000 if left_time and right_time else 0
    if hours > 72:
        return 0.0
    cosine = _cosine(left_vector, right_vector)
    overlap = _distinctive_tokens(left) & _distinctive_tokens(right)
    left_events, right_events = _event_anchors(left), _event_anchors(right)
    if left_events and right_events and left_events.isdisjoint(right_events):
        return 0.0
    left_title = _normalized(left.get("title"))
    right_title = _normalized(right.get("title"))
    title_tokens = {
        token for token in left_title.split()
        if (len(token) >= 3 or token.isdigit()) and token not in GENERIC_TERMS
    } & {
        token for token in right_title.split()
        if (len(token) >= 3 or token.isdigit()) and token not in GENERIC_TERMS
    }
    title_similarity = bigram_similarity(left_title, right_title)
    shared_numbers = _numbers(left) & _numbers(right)
    number_bonus = 0.10 if shared_numbers and (left_events & right_events or title_tokens) else 0.0
    title_bonus = max(0.0, min(0.16, (title_similarity - 0.35) * 0.32))
    event_bonus = 0.08 if left_events & right_events else 0.0
    bonus = min(0.18, len(overlap) * 0.045) + number_bonus + title_bonus + event_bonus
    time_weight = 1.0 if hours <= 24 else 0.92 if hours <= 48 else 0.84
    score = min(1.0, cosine * time_weight + bonus)
    if not title_tokens and title_similarity < 0.25 and not (left_events & right_events and shared_numbers):
        return min(score, 0.39)
    return score


def _cluster_indexes(
    scores: dict[tuple[int, int], float],
    article_count: int,
    pair_threshold: float,
    minimum_cross_score: float,
) -> list[list[int]]:
    """강한 연결 하나만으로 서로 다른 사건이 연쇄 병합되지 않도록 군집 간 점수도 확인한다."""
    groups = {index: [index] for index in range(article_count)}
    cross_stats = {pair: (score, 1, score) for pair, score in scores.items()}
    while True:
        best: tuple[float, float, int, int] | None = None
        for (left, right), (total, count, minimum) in cross_stats.items():
            average = total / count
            if average < pair_threshold or minimum < minimum_cross_score:
                continue
            candidate = (average, minimum, left, right)
            if best is None or candidate > best:
                best = candidate
        if best is None:
            return sorted(groups.values(), key=lambda indexes: indexes[0])
        _, _, left, right = best

        combined_stats: dict[tuple[int, int], tuple[float, int, float]] = {}
        for other in groups.keys() - {left, right}:
            left_stats = cross_stats[tuple(sorted((left, other)))]
            right_stats = cross_stats[tuple(sorted((right, other)))]
            combined_stats[tuple(sorted((left, other)))] = (
                left_stats[0] + right_stats[0],
                left_stats[1] + right_stats[1],
                min(left_stats[2], right_stats[2]),
            )
        cross_stats = {
            pair: stats
            for pair, stats in cross_stats.items()
            if left not in pair and right not in pair
        }
        cross_stats.update(combined_stats)
        groups[left] = sorted(groups[left] + groups.pop(right))


def _priority(score: int) -> str:
    return "required" if score >= 75 else "review" if score >= 45 else "reference"


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def issue_status(published_times: list[str], as_of: datetime, first_seen: str | None = None) -> str:
    times = sorted(time for value in published_times if (time := _parse_time(value)))
    if not times:
        return "new"
    first = _parse_time(first_seen) or times[0]
    age_hours = (as_of - first).total_seconds() / 3600
    since_last = (as_of - times[-1]).total_seconds() / 3600
    if 0 <= age_hours <= 24:
        return "new"
    recent = sum(0 <= (as_of - time).total_seconds() <= 24 * 3600 for time in times)
    previous = sum(24 * 3600 < (as_of - time).total_seconds() <= 48 * 3600 for time in times)
    if recent >= 2 and recent > previous:
        return "expanding"
    if recent >= 1:
        return "ongoing"
    return "cooling" if since_last < 72 else "closed"


def build_clusters(
    articles: list[dict[str, Any]],
    as_of: datetime,
    pair_threshold: float = PAIR_THRESHOLD,
) -> list[dict[str, Any]]:
    if not articles:
        return []
    vectors = _tfidf_vectors(articles)
    scores: dict[tuple[int, int], float] = {}
    for left in range(len(articles)):
        for right in range(left + 1, len(articles)):
            score = pair_score(articles[left], articles[right], vectors[left], vectors[right])
            scores[(left, right)] = score
    minimum_cross_score = max(0.15, round(pair_threshold - 0.15, 2))
    groups = _cluster_indexes(scores, len(articles), pair_threshold, minimum_cross_score)

    clusters = []
    for indexes in groups:
        members = [articles[index] for index in indexes]
        representative = max(
            members,
            key=lambda item: (
                item.get("relevanceScore") or 0,
                item.get("severityScore") or 0,
                date_value(item.get("publishedAt")),
            ),
        )
        sources = {str(item.get("source") or "").strip() for item in members if item.get("source")}
        recent_count = sum(
            0 <= (as_of - published).total_seconds() <= 24 * 3600
            for item in members
            if (published := _parse_time(item.get("publishedAt")))
        )
        major = bool(sources & MAJOR_OUTLETS)
        spread = min(100, len(sources) * 12 + (20 if major else 0) + recent_count * 8)
        relevance = max((item.get("relevanceScore") or 0) for item in members)
        severity = max((item.get("severityScore") or 0) for item in members)
        priority_score = round(0.4 * relevance + 0.4 * severity + 0.2 * spread)
        member_ids = [item["id"] for item in members]
        member_scores = {}
        for index in indexes:
            related_scores = [
                scores[tuple(sorted((index, other)))] for other in indexes if other != index
            ]
            member_scores[articles[index]["id"]] = max(related_scores, default=1.0)
        published_times = [item.get("publishedAt") for item in members if item.get("publishedAt")]
        clusters.append(
            {
                "articleIds": member_ids,
                "representativeArticleId": representative["id"],
                "autoTitle": representative["title"],
                "autoStatus": issue_status(published_times, as_of),
                "autoPriority": _priority(priority_score),
                "autoPriorityScore": priority_score,
                "spreadScore": spread,
                "directMention": any(item.get("directMention") for item in members),
                "firstSeenAt": min(published_times) if published_times else None,
                "lastSeenAt": max(published_times) if published_times else None,
                "membershipScores": member_scores,
                "autoReasons": {
                    "algorithmVersion": ALGORITHM_VERSION,
                    "clustering": {
                        "pairThreshold": pair_threshold,
                        "minimumCrossScore": minimum_cross_score,
                    },
                    "spread": {
                        "distinctSourceCount": len(sources),
                        "majorOutletIncluded": major,
                        "recent24hArticleCount": recent_count,
                        "score": spread,
                    },
                    "priority": {
                        "relevanceScore": relevance,
                        "severityScore": severity,
                        "spreadScore": spread,
                        "weights": {"relevance": 0.4, "severity": 0.4, "spread": 0.2},
                        "score": priority_score,
                    },
                },
            }
        )
    return sorted(clusters, key=lambda cluster: (cluster["lastSeenAt"] or "", cluster["autoTitle"]), reverse=True)


def build_proposal(
    clusters: list[dict[str, Any]], existing_issues: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """기사 집합 겹침을 우선해 기존 issue_id를 안정적으로 재사용하고 diff를 만든다."""
    existing_sets = {
        issue["id"]: set(issue.get("effectiveArticleIds") or []) for issue in existing_issues
    }
    candidates: list[tuple[float, int, str]] = []
    overlap_by_cluster: dict[int, list[str]] = {}
    overlap_clusters_by_issue: dict[str, list[int]] = {}
    for index, cluster in enumerate(clusters):
        article_ids = set(cluster["articleIds"])
        for issue_id, previous_ids in existing_sets.items():
            overlap = article_ids & previous_ids
            if not overlap:
                continue
            union = article_ids | previous_ids
            candidates.append((len(overlap) / len(union), index, issue_id))
            overlap_by_cluster.setdefault(index, []).append(issue_id)
            overlap_clusters_by_issue.setdefault(issue_id, []).append(index)

    claimed_clusters: set[int] = set()
    claimed_issues: set[str] = set()
    for _, index, issue_id in sorted(candidates, reverse=True):
        if index in claimed_clusters or issue_id in claimed_issues:
            continue
        clusters[index]["existingIssueId"] = issue_id
        claimed_clusters.add(index)
        claimed_issues.add(issue_id)

    clusters_by_existing: dict[str, list[int]] = {}
    moved_articles = []
    for index, cluster in enumerate(clusters):
        issue_id = cluster.get("existingIssueId")
        if issue_id:
            clusters_by_existing.setdefault(issue_id, []).append(index)
            before = existing_sets[issue_id]
            after = set(cluster["articleIds"])
            moved_articles.extend(
                {"articleId": article_id, "fromIssueId": issue_id, "toIssueId": None}
                for article_id in sorted(before - after)
            )
            moved_articles.extend(
                {"articleId": article_id, "fromIssueId": None, "toIssueId": issue_id}
                for article_id in sorted(after - before)
            )

    matched = {cluster.get("existingIssueId") for cluster in clusters}
    orphaned = [
        issue["id"] for issue in existing_issues
        if issue["id"] not in matched and issue.get("hasEditorOverride")
    ]
    diff = {
        "createdIssues": [index for index, cluster in enumerate(clusters) if not cluster.get("existingIssueId")],
        "mergeCandidates": [
            {"clusterIndex": index, "issueIds": issue_ids}
            for index, issue_ids in overlap_by_cluster.items() if len(issue_ids) > 1
        ],
        "splitCandidates": [
            {"issueId": issue_id, "clusterIndexes": indexes}
            for issue_id, indexes in overlap_clusters_by_issue.items() if len(indexes) > 1
        ],
        "movedArticles": moved_articles,
        "preservedEditorOverrides": [
            issue["id"] for issue in existing_issues if issue.get("hasEditorOverride")
        ],
        "orphanedEditedIssues": orphaned,
    }
    return clusters, diff
