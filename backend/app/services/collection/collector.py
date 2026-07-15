from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from backend.app.core.clock import SEOUL_TZ, now_iso, today_seoul
from backend.app.repositories import article_repository as article_repo
from backend.app.repositories import run_repository as run_repo
from backend.app.repositories.database import get_connection
from backend.app.services.classification.rule_engine import infer_category, should_exclude
from backend.app.services.classification.service import CLASSIFIER_VERSION, classify_article, relevance_sort_key
from backend.app.services.collection.custom_endpoint import fetch_custom_endpoint
from backend.app.services.collection.gdelt import fetch_gdelt_combined
from backend.app.services.collection.google_news import fetch_google_rss
from backend.app.services.collection.http import CollectionHttpError
from backend.app.services.collection.rss_parser import RssParseError
from backend.app.services.collection.yonhap import fetch_yonhap_rss
from backend.app.services.deduplication.service import deduplicate_detailed
from backend.app.services.extraction.cleaner import clean_text
from backend.app.services.normalization.dates import date_value, since_bound_iso
from backend.app.services.normalization.url import canonical_article_url

Article = dict[str, Any]


def friendly_error(exc: BaseException) -> str:
    if isinstance(exc, (CollectionHttpError, RssParseError)):
        return str(exc)
    message = clean_text(str(exc)) or "알 수 없는 오류"
    return message


def _within_lookback(pub_date: str | None, report_date: str, lookback_hours: int) -> bool:
    value = date_value(pub_date)
    if not value:
        return True
    today = today_seoul()
    if report_date == today:
        target = datetime.now(SEOUL_TZ).timestamp() * 1000
    else:
        target = datetime.fromisoformat(f"{report_date}T23:59:59").replace(tzinfo=SEOUL_TZ).timestamp() * 1000
    return target - lookback_hours * 3600000 <= value <= target + 3600000


def fetch_query(
    query: dict[str, Any], endpoint: str, lookback_hours: int, max_records: int
) -> dict[str, Any]:
    query_text = query.get("query") or ""
    if endpoint.strip():
        try:
            items = fetch_custom_endpoint(endpoint, query_text, lookback_hours, max_records)
            return {"items": items, "provider": "기관용 뉴스 API"}
        except Exception as endpoint_error:  # noqa: BLE001 (JS와 동일하게 실패 사유를 합쳐 다음 provider로 폴백)
            try:
                items = fetch_google_rss(query_text, lookback_hours, max_records)
                return {
                    "items": items,
                    "provider": "Google 뉴스 RSS",
                    "warning": f"기관 API 연결 실패({friendly_error(endpoint_error)})로 공개 RSS를 사용했습니다.",
                }
            except Exception as rss_error:  # noqa: BLE001
                raise RuntimeError(
                    f"기관 API: {friendly_error(endpoint_error)} / RSS: {friendly_error(rss_error)}"
                ) from rss_error
    items = fetch_google_rss(query_text, lookback_hours, max_records)
    return {"items": items, "provider": "Google 뉴스 RSS"}


def _persist_provider_results(
    connection, run_id: str, provider_tasks: list[dict[str, Any]], started_at: str, finished_at: str
) -> dict[str, str]:
    provider_id_by_label: dict[str, str] = {}
    for task in provider_tasks:
        provider_id_by_label[task["label"]] = run_repo.add_provider_result(
            connection,
            run_id=run_id,
            provider=task.get("provider") or task["label"],
            query_group_id=task.get("query_group_id"),
            status=task["status"],
            started_at=started_at,
            finished_at=finished_at,
            raw_count=task.get("raw_count", 0),
            accepted_count=0,
            duplicate_count=0,
            warning_message=task.get("warning_message"),
            error_code=None,
            error_message=task.get("error_message"),
        )
    return provider_id_by_label


def _upsert_article_for_item(connection, item: Article) -> tuple[str, str, bool]:
    """content_key/제목 fuzzy 매칭으로 기존 기사와 병합하거나 새 기사를 만든다. (article_id, dedup_method, matched) 반환."""
    pub_date = item.get("pubDate")
    since = since_bound_iso(pub_date, 96)
    match = article_repo.find_matching_article(
        connection, url=item.get("url"), title=item.get("title"), published_at=pub_date, since_iso=since
    )
    if match is not None:
        article_id = match["id"]
        new_description = item.get("description") or ""
        if len(new_description) > len(match["description"] or ""):
            article_repo.touch_article(connection, article_id, description=new_description)
        else:
            article_repo.touch_article(connection, article_id)
        canonical = canonical_article_url(item.get("url"))
        dedup_method = "canonical_url" if canonical and canonical == match["canonical_url"] else "fuzzy_same_copy"
        return article_id, dedup_method, True

    article_id = article_repo.create_article(
        connection,
        url=item.get("url"),
        title=item.get("title") or "제목 없음",
        source=item.get("source"),
        published_at=pub_date,
        description=item.get("description"),
        category_hint=item.get("category"),
        manual=False,
    )
    return article_id, "new", False


async def run_collection(payload: dict[str, Any]) -> dict[str, Any]:
    report_date = payload.get("reportDate") or today_seoul()
    lookback_hours = int(payload.get("lookbackHours") or 48)
    max_records = int(payload.get("maxRecordsPerQuery") or 50)
    collection_limit = int(payload.get("collectionLimit") or 200)
    enable_yonhap = payload.get("enableYonhap") is not False
    queries = [q for q in (payload.get("queries") or []) if str(q.get("query") or "").strip()]
    core_keywords = [k for k in (payload.get("coreKeywords") or []) if k]
    risk_keywords = payload.get("riskKeywords") or []
    positive_keywords = payload.get("positiveKeywords") or []
    exclude_keywords = payload.get("excludeKeywords") or []
    endpoint = payload.get("endpoint") or ""

    def within_lookback(pub_date: str | None) -> bool:
        return _within_lookback(pub_date, report_date, lookback_hours)

    started_at = now_iso()

    tasks: list[tuple[str, str]] = []
    coros = []
    if enable_yonhap:
        tasks.append(("연합뉴스", "auto"))
        coros.append(asyncio.to_thread(fetch_yonhap_rss, within_lookback, collection_limit))
    for query in queries:
        tasks.append((str(query.get("label") or query.get("id") or "검색식"), str(query.get("id") or "direct")))
        coros.append(asyncio.to_thread(fetch_query, query, endpoint, lookback_hours, max_records))

    results = await asyncio.gather(*coros, return_exceptions=True) if coros else []

    collected: list[Article] = []
    providers: list[str] = []
    failures: list[str] = []
    warnings: list[str] = []
    provider_tasks: list[dict[str, Any]] = []

    for (label, category), result in zip(tasks, results):
        query_group_id = None if category == "auto" else category
        if isinstance(result, BaseException):
            failures.append(f"{label}: {friendly_error(result)}")
            provider_tasks.append(
                {
                    "label": label,
                    "provider": label,
                    "query_group_id": query_group_id,
                    "status": "failed",
                    "raw_count": 0,
                    "error_message": friendly_error(result),
                }
            )
            continue
        items = result["items"]
        for item in items:
            assigned_category = infer_category(item) if category == "auto" else category
            collected.append({**item, "category": assigned_category, "_task_label": label, "_query_group_id": query_group_id})
        provider_label = result.get("provider")
        if provider_label and provider_label not in providers:
            providers.append(provider_label)
        warning = result.get("warning")
        if warning:
            warnings.append(f"{label}: {warning}")
        provider_tasks.append(
            {
                "label": label,
                "provider": provider_label,
                "query_group_id": query_group_id,
                "status": "success",
                "raw_count": len(items),
                "warning_message": warning,
            }
        )

    network_succeeded = bool(providers)
    if not collected and failures:
        try:
            gdelt_items = await asyncio.to_thread(fetch_gdelt_combined, core_keywords, lookback_hours, max_records)
            for item in gdelt_items:
                collected.append(
                    {**item, "category": infer_category(item), "_task_label": "GDELT", "_query_group_id": None}
                )
            if "GDELT" not in providers:
                providers.append("GDELT")
            network_succeeded = True
            warnings.extend(f"RSS 보조 전환: {f}" for f in failures)
            provider_tasks.append(
                {
                    "label": "GDELT",
                    "provider": "GDELT",
                    "query_group_id": None,
                    "status": "success",
                    "raw_count": len(gdelt_items),
                }
            )
            failures = []
        except Exception as gdelt_error:  # noqa: BLE001
            failures.append(f"GDELT 보조: {friendly_error(gdelt_error)}")
            provider_tasks.append(
                {
                    "label": "GDELT",
                    "provider": "GDELT",
                    "query_group_id": None,
                    "status": "failed",
                    "raw_count": 0,
                    "error_message": friendly_error(gdelt_error),
                }
            )

    eligible = [
        article
        for article in collected
        if not should_exclude(article, exclude_keywords) and within_lookback(article.get("pubDate"))
    ]
    first_pass_items, duplicates_removed = deduplicate_detailed(eligible, risk_keywords, positive_keywords)

    classified_items = [classify_article(raw, risk_keywords, positive_keywords) for raw in first_pass_items]
    classified_items.sort(key=relevance_sort_key)
    classified_items = classified_items[:collection_limit]

    finished_at = now_iso()
    raw_count = len(collected)
    accepted_count = len(eligible)

    connection = get_connection()
    try:
        with connection:
            run_id = run_repo.create_run(
                connection, report_date=report_date, started_at=started_at, lookback_hours=lookback_hours
            )
            provider_id_by_label = _persist_provider_results(connection, run_id, provider_tasks, started_at, finished_at)

            if not network_succeeded:
                run_repo.finish_run(
                    connection,
                    run_id,
                    status="failed",
                    finished_at=finished_at,
                    raw_count=raw_count,
                    accepted_count=0,
                    unique_count=0,
                    stale_reused_count=len(run_repo.unrefreshed_candidate_ids(connection, report_date, run_id)),
                    warning_count=len(warnings),
                    error_count=len(failures),
                )
                return {
                    "status": "failed",
                    "provider": "수집 실패",
                    "rawCollectedCount": raw_count,
                    "uniqueCount": 0,
                    "duplicatesRemoved": 0,
                    "fetchedAt": finished_at,
                    "errors": failures or ["데이터 제공 경로에서 응답을 받지 못했습니다."],
                    "warnings": warnings,
                    "collectionRunId": run_id,
                }

            new_count = 0
            matched_count = 0
            for item in classified_items:
                article_id, dedup_method, matched = _upsert_article_for_item(connection, item)
                if matched:
                    matched_count += 1
                else:
                    new_count += 1
                article_repo.insert_observation(
                    connection,
                    article_id=article_id,
                    collection_run_provider_id=provider_id_by_label.get(item.get("_task_label")),
                    provider=item.get("provider") or item.get("_task_label") or "unknown",
                    provider_item_key=None,
                    query_group_id=item.get("_query_group_id"),
                    raw_url=item.get("url"),
                    raw_title=item.get("title"),
                    raw_source=item.get("source"),
                    raw_published_at=item.get("pubDate"),
                    raw_description=item.get("description"),
                    raw_payload_json=None,
                    dedup_method=dedup_method,
                    dedup_score=None,
                )
                article_repo.upsert_assessment(
                    connection,
                    article_id=article_id,
                    assessment={**item["assessment"], "autoCategory": item.get("category")},
                    classifier_version=CLASSIFIER_VERSION,
                )

            status = "success" if not failures else "partial"
            stale_reused_count = len(run_repo.unrefreshed_candidate_ids(connection, report_date, run_id))
            run_repo.finish_run(
                connection,
                run_id,
                status=status,
                finished_at=finished_at,
                raw_count=raw_count,
                accepted_count=accepted_count,
                unique_count=len(classified_items),
                stale_reused_count=stale_reused_count,
                warning_count=len(warnings),
                error_count=len(failures),
            )
    finally:
        connection.close()

    return {
        "status": status,
        "provider": " + ".join(providers),
        "rawCollectedCount": raw_count,
        "uniqueCount": len(classified_items),
        "newCount": new_count,
        "matchedCount": matched_count,
        "duplicatesRemoved": duplicates_removed,
        "fetchedAt": finished_at,
        "errors": [],
        "warnings": [*warnings, *(f"일부 검색 실패: {f}" for f in failures)],
        "collectionRunId": run_id,
    }
