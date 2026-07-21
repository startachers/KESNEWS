from __future__ import annotations

import logging
import os
from typing import Any

from backend.app.core.clock import now_iso
from backend.app.repositories import article_repository as article_repo
from backend.app.repositories import briefing_repository as briefing_repo
from backend.app.repositories import issue_repository as issue_repo
from backend.app.repositories import run_repository as run_repo
from backend.app.repositories.database import get_connection
from backend.app.services.analysis_markdown.replacement_finder import (
    rank_related_candidates,
    related_query_variants,
    search_related_candidates,
)
from backend.app.services.classification.service import CLASSIFIER_VERSION, classify_article
from backend.app.services.collection.naver_news import fetch_naver_news
from backend.app.services.normalization.dates import date_value, since_bound_iso


logger = logging.getLogger("kesco.related_search")


class RelatedSearchNotFound(LookupError):
    pass


def _target_issue(connection, report_date: str, article_id: str) -> dict[str, Any] | None:
    return next(
        (issue for issue in issue_repo.list_for_report_date(connection, report_date)
         if article_id in (issue.get("articleIds") or [])),
        None,
    )


def _search_sources(original: dict, report_date: str) -> tuple[list[dict], list[str]]:
    combined: list[dict] = []
    sources: list[str] = []
    failures: list[Exception] = []
    try:
        google_items = search_related_candidates(original, lookback_hours=2160, limit=50)
    except Exception as exc:
        failures.append(exc)
        logger.warning("관련기사 Google 보강 검색 실패: %s", exc)
    else:
        combined.extend(google_items)
        sources.append("Google 뉴스 RSS")
    client_id = os.environ.get("NAVER_CLIENT_ID", "").strip()
    client_secret = os.environ.get("NAVER_CLIENT_SECRET", "").strip()
    if client_id and client_secret:
        report_end = date_value(f"{report_date}T23:59:59+09:00")
        reference = date_value(original.get("pubDate")) or report_end
        lower = reference - 2160 * 3600000
        upper = report_end + 24 * 3600000
        naver_items: list[dict] = []
        try:
            for query in related_query_variants(original)[:3]:
                naver_items.extend(fetch_naver_news(
                    query,
                    client_id,
                    client_secret,
                    lambda value: lower <= date_value(value) <= upper,
                    max_pages=1,
                ))
        except Exception as exc:  # 네이버 실패 시 Google 결과는 그대로 사용한다.
            failures.append(exc)
            logger.warning("관련기사 네이버 보강 검색 실패: %s", exc)
        else:
            combined.extend(naver_items)
            sources.append("네이버 뉴스 API")
    if not sources and failures:
        raise failures[0]
    return rank_related_candidates(original, combined, limit=10), sources


def search_and_attach(
    report_date: str,
    article_id: str,
    expected_revision: int,
) -> dict[str, Any]:
    connection = get_connection()
    try:
        briefing = briefing_repo.get_by_date(connection, report_date)
        if briefing is None:
            raise briefing_repo.BriefingNotFound()
        if briefing["status"] == "final":
            raise briefing_repo.BriefingFinalized()
        if briefing["revision"] != expected_revision:
            raise briefing_repo.RevisionConflict()
        candidates = article_repo.list_candidates(connection, report_date, include_dismissed=True)
        original = next((item for item in candidates if item["id"] == article_id), None)
        if original is None:
            raise RelatedSearchNotFound(article_id)
        existing_issue = _target_issue(connection, report_date, article_id)
    finally:
        connection.close()

    searched, search_sources = _search_sources(original, report_date)
    started_at = now_iso()
    connection = get_connection()
    try:
        with connection:
            briefing = briefing_repo.get_by_date(connection, report_date)
            if briefing is None:
                raise briefing_repo.BriefingNotFound()
            if briefing["status"] == "final":
                raise briefing_repo.BriefingFinalized()
            if briefing["revision"] != expected_revision:
                raise briefing_repo.RevisionConflict()

            run_id = run_repo.create_run(
                connection, report_date=report_date, started_at=started_at, lookback_hours=720
            )
            finished_at = now_iso()
            provider_id = run_repo.add_provider_result(
                connection,
                run_id=run_id,
                provider=" + ".join(f"{source} (관련기사 검색)" for source in search_sources),
                query_group_id=f"related:{article_id}",
                status="success",
                started_at=started_at,
                finished_at=finished_at,
                raw_count=len(searched),
                accepted_count=len(searched),
                duplicate_count=0,
                warning_message=None,
                error_code=None,
                error_message=None,
            )
            found_ids: list[str] = []
            new_count = 0
            for item in searched[:10]:
                classified = classify_article({
                    **item,
                    "category": original.get("category"),
                    "manual": False,
                })
                existing = article_repo.find_matching_article(
                    connection,
                    url=item.get("url"),
                    title=item.get("title") or "",
                    published_at=item.get("pubDate"),
                    since_iso=since_bound_iso(item.get("pubDate"), 24 * 365),
                )
                if existing is None:
                    found_id = article_repo.create_article(
                        connection,
                        url=item.get("url"),
                        title=item.get("title") or "제목 없음",
                        source=item.get("source"),
                        published_at=item.get("pubDate"),
                        description=item.get("description"),
                        category_hint=classified.get("category"),
                        manual=False,
                        publisher_id=item.get("publisherId"),
                        publisher_allowed=True,
                    )
                    new_count += 1
                else:
                    found_id = existing["id"]
                    article_repo.touch_article(
                        connection,
                        found_id,
                        description=item.get("description"),
                        publisher_id=item.get("publisherId"),
                        publisher_allowed=True,
                    )
                article_repo.insert_observation(
                    connection,
                    article_id=found_id,
                    collection_run_provider_id=provider_id,
                    provider=f"{item.get('provider') or '관련기사 검색'} (관련기사 검색)",
                    provider_item_key=None,
                    query_group_id=f"related:{article_id}",
                    raw_url=item.get("url"),
                    raw_title=item.get("title"),
                    raw_source=item.get("source"),
                    raw_published_at=item.get("pubDate"),
                    raw_description=item.get("description"),
                    raw_payload_json=None,
                    dedup_method="related_search" if existing is None else "related_search_existing",
                    dedup_score=None,
                )
                article_repo.upsert_assessment(
                    connection,
                    article_id=found_id,
                    assessment={**classified["assessment"], "autoCategory": classified.get("category")},
                    classifier_version=CLASSIFIER_VERSION,
                )
                if found_id != article_id and found_id not in found_ids:
                    found_ids.append(found_id)

            issue_id = existing_issue["id"] if existing_issue else None
            added_ids: list[str] = []
            if found_ids:
                if issue_id is None:
                    issue_id = issue_repo.create_manual_group(
                        connection, report_date, [article_id, *found_ids]
                    )
                    added_ids = found_ids
                else:
                    current_ids = set((issue_repo.serialize_one(connection, issue_id) or {}).get("articleIds") or [])
                    for found_id in found_ids:
                        if found_id in current_ids:
                            continue
                        issue_repo.set_membership_override(connection, issue_id, found_id, "add")
                        added_ids.append(found_id)
                issue_repo.recalculate_review_assessments(connection, report_date)

            run_repo.finish_run(
                connection,
                run_id,
                status="success",
                finished_at=finished_at,
                raw_count=len(searched),
                accepted_count=len(found_ids),
                unique_count=len(found_ids),
                stale_reused_count=0,
                warning_count=0,
                error_count=0,
                source_filter_stats={
                    "trusted_media": sum(
                        item.get("relatedSearchPublisherScope") == "trusted"
                        for item in searched[:10]
                    ),
                    "related_search_domain_identified": sum(
                        item.get("relatedSearchPublisherScope") == "domain_identified"
                        for item in searched[:10]
                    ),
                    "related_search_relaxed": len(found_ids),
                },
            )
            updated = (
                briefing_repo.bump_revision(connection, briefing["id"], expected_revision)
                if found_ids else briefing
            )
        return {
            "articleId": article_id,
            "issueId": issue_id,
            "foundCount": len(found_ids),
            "addedCount": len(added_ids),
            "newArticleCount": new_count,
            "articleIds": found_ids,
            "revision": updated["revision"],
            "policy": {
                "lookbackHours": 2160,
                "maxResults": 10,
                "sources": search_sources,
                "relaxed": ["query_group_relevance", "exclude_keywords", "daily_lookback"],
                "preserved": ["publisher_domain_identity", "source_validation"],
            },
        }
    finally:
        connection.close()
