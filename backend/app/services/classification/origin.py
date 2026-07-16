from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from backend.app.services.deduplication.fuzzy import bigram_similarity

CLASSIFIER_VERSION = "kesco-press-origin-v1"
_GENERIC = {
    "한국전기안전공사", "전기안전공사", "kesco", "공사", "기자", "보도자료",
    "밝혔다", "위한", "대해", "통해", "이번", "관련", "진행", "실시",
}


def _normalized(value: str | None) -> str:
    return re.sub(r"[^0-9a-z가-힣]+", " ", str(value or "").lower()).strip()


def _compact(value: str | None) -> str:
    return _normalized(value).replace(" ", "")


def _tokens(value: str | None) -> set[str]:
    return {
        token
        for token in _normalized(value).split()
        if len(token) >= 2 and token not in _GENERIC
    }


def _timestamp(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()
    except ValueError:
        return None


def assess_kesco_origin(
    article: dict[str, Any], releases: list[dict[str, Any]]
) -> dict[str, Any] | None:
    article_title = _compact(article.get("title"))
    article_text = " ".join(
        str(article.get(field) or "") for field in ("title", "description", "bodyText")
    )
    article_tokens = _tokens(article_text)
    article_time = _timestamp(article.get("pubDate") or article.get("publishedAt"))
    best: dict[str, Any] | None = None
    for release in releases:
        release_time = _timestamp(release.get("publishedAt"))
        if article_time and release_time:
            delta_hours = (article_time - release_time) / 3600
            if delta_hours < -12 or delta_hours > 24 * 30:
                continue
        title_similarity = bigram_similarity(article_title, _compact(release.get("title")))
        release_tokens = _tokens(f"{release.get('title', '')} {release.get('bodyText', '')}")
        shared = article_tokens & release_tokens
        token_coverage = len(shared) / max(1, len(article_tokens))
        confidence = min(1.0, 0.68 * title_similarity + 0.32 * token_coverage)
        origin_type = None
        if title_similarity >= 0.78 or (
            title_similarity >= 0.58 and token_coverage >= 0.62
        ):
            origin_type = "kesco_republication"
        elif (
            title_similarity >= 0.48 and token_coverage >= 0.38 and len(shared) >= 3
        ) or (token_coverage >= 0.62 and len(shared) >= 5):
            origin_type = "kesco_based"
        if not origin_type:
            continue
        candidate = {
            "originType": origin_type,
            "pressReleaseId": release["id"],
            "confidence": round(confidence, 4),
            "reasons": {
                "titleSimilarity": round(title_similarity, 4),
                "tokenCoverage": round(token_coverage, 4),
                "sharedTerms": sorted(shared)[:20],
            },
        }
        if best is None or candidate["confidence"] > best["confidence"]:
            best = candidate
    return best
