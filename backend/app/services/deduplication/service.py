from __future__ import annotations

from typing import Any

from backend.app.services.classification.service import classify_article
from backend.app.services.deduplication.fuzzy import bigram_similarity
from backend.app.services.media import is_yonhap_article
from backend.app.services.normalization.dates import date_value
from backend.app.services.normalization.title import normalized_article_title
from backend.app.services.normalization.url import canonical_article_url

Article = dict[str, Any]


def article_preference(article: Article) -> float:
    return (
        (1000 if article.get("manual") else 0)
        + (500 if is_yonhap_article(article) else 0)
        + min(len(article.get("description") or ""), 300)
        + date_value(article.get("pubDate")) / 1e13
    )


def same_article(a: Article, b: Article) -> bool:
    # 공식 수집기의 sourceId는 각 부처가 부여한 보도자료 식별자다. 같은 수집기에서
    # 식별자가 다른 자료는 제목이 매우 비슷해도 서로 다른 보도자료로 보존한다.
    if a.get("_official_government") is True and b.get("_official_government") is True:
        left_provider = str(a.get("provider") or "")
        right_provider = str(b.get("provider") or "")
        left_source_id = str(a.get("sourceId") or "")
        right_source_id = str(b.get("sourceId") or "")
        if (
            left_provider
            and left_provider == right_provider
            and left_source_id
            and right_source_id
        ):
            return left_source_id == right_source_id
    left_url = canonical_article_url(a.get("url"))
    right_url = canonical_article_url(b.get("url"))
    if left_url and right_url and left_url == right_url:
        return True
    left_title = normalized_article_title(a.get("title"))
    right_title = normalized_article_title(b.get("title"))
    if not left_title or not right_title:
        return False
    if left_title == right_title:
        return True
    if min(len(left_title), len(right_title)) < 16:
        return False
    left_date = date_value(a.get("pubDate"))
    right_date = date_value(b.get("pubDate"))
    if left_date and right_date and abs(left_date - right_date) > 72 * 3600000:
        return False
    return bigram_similarity(left_title, right_title) >= 0.9


def merge_duplicate_articles(left: Article, right: Article) -> Article:
    preference = right if article_preference(right) > article_preference(left) else left
    other = right if preference is left else left
    longer_description = left.get("description") or "" if len(left.get("description") or "") >= len(
        right.get("description") or ""
    ) else right.get("description") or ""
    merged: Article = {**other, **preference}
    merged["description"] = longer_description or preference.get("description") or ""
    merged["included"] = bool(left.get("included") or right.get("included"))
    merged["starred"] = bool(left.get("starred") or right.get("starred"))
    merged["note"] = left.get("note") or right.get("note") or ""
    merged["matchedKeywords"] = list(
        dict.fromkeys([*(left.get("matchedKeywords") or []), *(right.get("matchedKeywords") or [])])
    )[:8]
    merged["duplicateSources"] = list(
        dict.fromkeys(
            [
                *(left.get("duplicateSources") or []),
                *(right.get("duplicateSources") or []),
                *([left["source"]] if left.get("source") else []),
                *([right["source"]] if right.get("source") else []),
            ]
        )
    )
    merged["_observations"] = [
        *(left.get("_observations") or [left]),
        *(right.get("_observations") or [right]),
    ]
    return merged


def deduplicate_detailed(
    items: list[Article], risk_keywords: list[str], positive_keywords: list[str]
) -> tuple[list[Article], int]:
    unique: list[Article] = []
    removed = 0
    for item in items:
        classified = item if item.get("risk") else classify_article(item, risk_keywords, positive_keywords)
        index = next((i for i, existing in enumerate(unique) if same_article(existing, classified)), -1)
        if index < 0:
            unique.append(classified)
        else:
            unique[index] = merge_duplicate_articles(unique[index], classified)
            removed += 1
    return unique, removed
