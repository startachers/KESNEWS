from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from backend.app.core.clock import SEOUL_TZ, now_iso, today_seoul
from backend.app.services.classification.rule_engine import infer_category, should_exclude
from backend.app.services.classification.service import classify_article, relevance_sort_key
from backend.app.services.collection.custom_endpoint import fetch_custom_endpoint
from backend.app.services.collection.gdelt import fetch_gdelt_combined
from backend.app.services.collection.google_news import fetch_google_rss
from backend.app.services.collection.http import CollectionHttpError
from backend.app.services.collection.rss_parser import RssParseError
from backend.app.services.collection.yonhap import fetch_yonhap_rss
from backend.app.services.deduplication.service import deduplicate_detailed, same_article
from backend.app.services.extraction.cleaner import clean_text
from backend.app.services.normalization.dates import date_value

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
    existing_articles: list[Article] = payload.get("existingArticles") or []

    def within_lookback(pub_date: str | None) -> bool:
        return _within_lookback(pub_date, report_date, lookback_hours)

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

    for (label, category), result in zip(tasks, results):
        if isinstance(result, BaseException):
            failures.append(f"{label}: {friendly_error(result)}")
            continue
        for item in result["items"]:
            assigned_category = infer_category(item) if category == "auto" else category
            collected.append({**item, "category": assigned_category})
        provider_label = result.get("provider")
        if provider_label and provider_label not in providers:
            providers.append(provider_label)
        warning = result.get("warning")
        if warning:
            warnings.append(f"{label}: {warning}")

    network_succeeded = bool(providers)
    if not collected and failures:
        try:
            gdelt_items = await asyncio.to_thread(fetch_gdelt_combined, core_keywords, lookback_hours, max_records)
            for item in gdelt_items:
                collected.append({**item, "category": infer_category(item)})
            if "GDELT" not in providers:
                providers.append("GDELT")
            network_succeeded = True
            warnings.extend(f"RSS 보조 전환: {f}" for f in failures)
            failures = []
        except Exception as gdelt_error:  # noqa: BLE001
            failures.append(f"GDELT 보조: {friendly_error(gdelt_error)}")

    eligible = [
        article
        for article in collected
        if not should_exclude(article, exclude_keywords) and within_lookback(article.get("pubDate"))
    ]
    first_pass_items, first_pass_removed = deduplicate_detailed(eligible, risk_keywords, positive_keywords)

    fresh: list[Article] = []
    for raw in first_pass_items:
        classified = classify_article(raw, risk_keywords, positive_keywords)
        old = next((a for a in existing_articles if same_article(a, classified)), None)
        fresh.append(
            {
                **classified,
                "included": bool(old.get("included")) if old else False,
                "starred": bool(old.get("starred")) if old else False,
                "note": (old.get("note") if old else "") or "",
            }
        )
    fresh.sort(key=relevance_sort_key)
    fresh = fresh[:collection_limit]

    finished_at = now_iso()

    if network_succeeded:
        manual = [a for a in existing_articles if a.get("manual")]
        final_items, final_removed = deduplicate_detailed(manual + fresh, risk_keywords, positive_keywords)
        final_items.sort(key=relevance_sort_key)
        status = "success" if not failures else "partial"
        return {
            "status": status,
            "provider": " + ".join(providers),
            "articles": final_items,
            "rawCollectedCount": len(collected),
            "duplicatesRemoved": first_pass_removed + final_removed,
            "fetchedAt": finished_at,
            "errors": [],
            "warnings": [*warnings, *(f"일부 검색 실패: {f}" for f in failures)],
        }

    return {
        "status": "failed",
        "provider": "수집 실패",
        "articles": [],
        "rawCollectedCount": len(collected),
        "duplicatesRemoved": 0,
        "fetchedAt": finished_at,
        "errors": failures or ["데이터 제공 경로에서 응답을 받지 못했습니다."],
        "warnings": warnings,
    }
