from __future__ import annotations

import asyncio
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from backend.app.core.clock import SEOUL_TZ, now_iso, today_seoul
from backend.app.repositories import article_repository as article_repo
from backend.app.repositories import press_release_repository as press_release_repo
from backend.app.repositories import run_repository as run_repo
from backend.app.repositories.database import get_connection
from backend.app.services.classification.rule_engine import infer_category, should_exclude
from backend.app.services.classification.sentinel import detect_incident_sentinel
from backend.app.services.classification.service import (
    CLASSIFIER_VERSION,
    classify_article,
    get_relevance,
    relevance_sort_key,
)
from backend.app.services.classification.origin import (
    CLASSIFIER_VERSION as ORIGIN_CLASSIFIER_VERSION,
    assess_kesco_origin,
)
from backend.app.services.collection.custom_endpoint import fetch_custom_endpoint
from backend.app.services.collection.gdelt import fetch_gdelt_combined
from backend.app.services.collection.google_news import fetch_google_rss
from backend.app.services.collection.http import CollectionHttpError
from backend.app.services.collection.me_press import fetch_me_press
from backend.app.services.collection.naver_news import NAVER_PROVIDER, fetch_naver_news
from backend.app.services.collection.opm_press import fetch_opm_press
from backend.app.services.collection.policy_briefing import fetch_policy_briefing
from backend.app.services.collection.rss_parser import RssParseError
from backend.app.services.collection.yonhap import fetch_yonhap_rss
from backend.app.services.deduplication.service import deduplicate_detailed
from backend.app.services.extraction.cleaner import clean_text
from backend.app.services.media import identify_trusted_publisher, load_trusted_media_config
from backend.app.services.normalization.dates import date_value, since_bound_iso
from backend.app.services.normalization.content_key import make_content_key
from backend.app.services.normalization.url import canonical_article_url

Article = dict[str, Any]
PEOPLE_CONFIG_PATH = Path(__file__).resolve().parents[4] / "config" / "people.yaml"
_PEOPLE_KEYS = ("president", "prime_minister", "climate_minister")
GOVERNMENT_DIRECT_PROVIDERS = {
    "국무조정실 보도자료",
    "기후에너지환경부 보도자료",
    "정책브리핑 API",
}
DATE_ONLY_GOVERNMENT_PROVIDERS = {
    "국무조정실 보도자료",
    "기후에너지환경부 보도자료",
}


def _load_people(path: Path | None = None) -> dict[str, str]:
    """추가 YAML 의존성 없이 people.yaml의 단순 문자열 필드만 읽는다."""
    config_path = path or PEOPLE_CONFIG_PATH
    try:
        raw = config_path.read_text(encoding="utf-8")
    except OSError:
        return {key: "" for key in _PEOPLE_KEYS}
    result = {key: "" for key in _PEOPLE_KEYS}
    for key in _PEOPLE_KEYS:
        match = re.search(rf"^\s*{key}:\s*(.*?)\s*(?:#.*)?$", raw, re.MULTILINE)
        if not match:
            continue
        value = match.group(1).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        result[key] = value.replace("\\", "").replace('"', "").strip()
    return result


def replace_people_tokens(
    queries: list[dict[str, Any]], path: Path | None = None
) -> list[dict[str, Any]]:
    people = _load_people(path)
    replacements = {
        f"{{OR_current_{key}}}": f' OR "{value}"' if value else ""
        for key, value in people.items()
    }
    replaced = []
    for query in queries:
        query_text = str(query.get("query") or "")
        for token, value in replacements.items():
            query_text = query_text.replace(token, value)
        replaced.append({**query, "query": query_text})
    return replaced


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
    return target - lookback_hours * 3600000 <= value <= target


def _within_date_only_government_window(pub_date: str | None, report_date: str) -> bool:
    """시각을 제공하지 않는 정부 게시판은 보고일·전일의 서울 날짜만 허용한다.

    날짜만으로는 정확한 24시간 경계를 계산할 수 없으므로 전일 자료가 오전 9시에 일괄
    만료되는 오판을 피하고, 2일 전 자료부터 제외한다.
    """
    value = date_value(pub_date)
    if not value:
        return True
    try:
        target_date = date.fromisoformat(report_date)
    except ValueError:
        return False
    published_date = datetime.fromtimestamp(value / 1000, SEOUL_TZ).date()
    return target_date - timedelta(days=1) <= published_date <= target_date


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


def fetch_naver_query(
    query_text: str,
    client_id: str,
    client_secret: str,
    within_lookback,
    max_records: int,
) -> dict[str, Any]:
    return {
        "items": fetch_naver_news(
            query_text, client_id, client_secret, within_lookback
        )[:max_records],
        "provider": NAVER_PROVIDER,
    }


def query_max_records(query: dict[str, Any], default: int) -> int:
    """검색군별 양의 정수 override가 있으면 사용하고, 아니면 전역 기본값을 유지한다."""
    try:
        value = int(query.get("maxRecords"))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _persist_provider_results(
    connection, run_id: str, provider_tasks: list[dict[str, Any]], started_at: str, finished_at: str
) -> dict[str, str]:
    provider_id_by_label: dict[str, str] = {}
    for task in provider_tasks:
        provider_id_by_label[task.get("key") or task["label"]] = run_repo.add_provider_result(
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
    # insert_observation과 동일한 provider 식별 규칙을 써야 source_id 매칭이 어긋나지 않는다.
    provider_label = item.get("provider") or item.get("_task_label") or "unknown"
    match = article_repo.find_matching_article(
        connection,
        url=item.get("url"),
        title=item.get("title"),
        published_at=pub_date,
        since_iso=since,
        provider=provider_label,
        provider_item_key=item.get("sourceId"),
        allow_fuzzy=not (
            item.get("_official_government") is True and bool(item.get("sourceId"))
        ),
    )
    dedup_method = ""
    if match is None:
        content_key = make_content_key(
            item.get("url"), item.get("title"), item.get("source"), pub_date
        )
        match = article_repo.find_by_content_key(connection, content_key)
        if match is not None:
            dedup_method = "content_key"
    if match is not None:
        article_id = match["id"]
        new_description = item.get("description") or ""
        if len(new_description) > len(match["description"] or ""):
            article_repo.touch_article(
                connection,
                article_id,
                description=new_description,
                publisher_id=item.get("publisherId"),
                publisher_allowed=item.get("publisherAllowed"),
            )
        else:
            article_repo.touch_article(
                connection,
                article_id,
                publisher_id=item.get("publisherId"),
                publisher_allowed=item.get("publisherAllowed"),
            )
        if not dedup_method:
            canonical = canonical_article_url(item.get("url"))
            dedup_method = (
                "canonical_url"
                if canonical and canonical == match["canonical_url"]
                else "fuzzy_same_copy"
            )
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
        publisher_id=item.get("publisherId"),
        publisher_allowed=item.get("publisherAllowed"),
    )
    return article_id, "new", False


def filter_trusted_sources(items: list[Article]) -> tuple[list[Article], dict[str, int]]:
    config = load_trusted_media_config()
    stats = {
        "raw_results": len(items),
        "official_sources": 0,
        "trusted_media": 0,
        "rejected_untrusted_media": 0,
        "unknown_publisher": 0,
    }
    accepted: list[Article] = []
    for article in items:
        incident = detect_incident_sentinel(article)
        decision = identify_trusted_publisher(
            article, config=config, incident_matched=bool(incident["matched"])
        )
        if not decision.allowed:
            stats["rejected_untrusted_media"] += 1
            if decision.reason == "unknown_publisher":
                stats["unknown_publisher"] += 1
            continue
        stats["official_sources" if decision.reason == "official_source" else "trusted_media"] += 1
        accepted.append(
            {
                **article,
                "publisherId": decision.publisher_id,
                "publisherAllowed": True,
                "_official_government": article.get("provider")
                in GOVERNMENT_DIRECT_PROVIDERS,
                "_publisher_hostname": decision.hostname,
                "_sentinel": incident,
            }
        )
    return accepted, stats


def apply_collection_limit(items: list[Article], collection_limit: int) -> list[Article]:
    """Sentinel·rank 1은 모두 보존하고 남은 자리만 관련도순으로 채운다."""
    protected = [
        item
        for item in items
        if item["_sentinel"]["matched"]
        or item["assessment"]["autoReasons"]["relevanceRank"] == 1
        or item.get("_official_government") is True
    ]
    protected_ids = {id(item) for item in protected}
    remaining = [item for item in items if id(item) not in protected_ids]
    return protected + remaining[: max(0, collection_limit - len(protected))]


async def run_collection(payload: dict[str, Any]) -> dict[str, Any]:
    report_date = payload.get("reportDate") or today_seoul()
    # 일일 브리핑 후보는 실행 시각 기준 24시간으로 고정한다. 구버전 클라이언트가
    # 48/72시간을 보내더라도 이전 브리핑 구간의 기사를 다시 수집하지 않는다.
    lookback_hours = 24
    max_records = int(payload.get("maxRecordsPerQuery") or 50)
    collection_limit = int(payload.get("collectionLimit") or 400)
    enable_yonhap = payload.get("enableYonhap") is not False
    # 구버전 프런트가 새 필드를 보내지 않아도 직접 수집은 기본 활성화한다.
    # 명시적으로 false를 보낸 경우에만 끈다.
    enable_opm_press = payload.get("enableOpmPress") is not False
    enable_me_press = payload.get("enableMePress") is not False
    enable_policy_briefing = payload.get("enablePolicyBriefing") is not False
    enable_media_fallback = payload.get("enableMediaFallback") is not False
    # 자격정보는 프런트·요청 바디에 노출하지 않는다(NC-004와 동일 원칙). 서버 환경변수로만 읽는다.
    policy_briefing_service_key = os.environ.get("POLICY_BRIEFING_SERVICE_KEY", "").strip()
    naver_client_id = os.environ.get("NAVER_CLIENT_ID", "").strip()
    naver_client_secret = os.environ.get("NAVER_CLIENT_SECRET", "").strip()
    naver_configured = bool(naver_client_id and naver_client_secret)
    queries = replace_people_tokens(
        [q for q in (payload.get("queries") or []) if str(q.get("query") or "").strip()]
    )
    core_keywords = [k for k in (payload.get("coreKeywords") or []) if k]
    risk_keywords = payload.get("riskKeywords") or []
    positive_keywords = payload.get("positiveKeywords") or []
    exclude_keywords = payload.get("excludeKeywords") or []
    endpoint = payload.get("endpoint") or ""

    def within_lookback(article: Article) -> bool:
        if (
            article.get("_official_government") is True
            and article.get("provider") in DATE_ONLY_GOVERNMENT_PROVIDERS
        ):
            return _within_date_only_government_window(article.get("pubDate"), report_date)
        return _within_lookback(article.get("pubDate"), report_date, lookback_hours)

    started_at = now_iso()

    tasks: list[dict[str, Any]] = []
    coros = []
    if enable_yonhap:
        tasks.append({"key": "yonhap", "label": "연합뉴스", "category": "auto"})
        coros.append(asyncio.to_thread(fetch_yonhap_rss, within_lookback, collection_limit))
    if enable_opm_press:
        tasks.append(
            {"key": "opm_press", "label": "국무조정실 보도자료", "category": "auto"}
        )
        coros.append(asyncio.to_thread(fetch_opm_press, max_records))
    if enable_me_press:
        tasks.append(
            {"key": "me_press", "label": "기후에너지환경부 보도자료", "category": "auto"}
        )
        coros.append(asyncio.to_thread(fetch_me_press, max_records))
    if enable_policy_briefing and policy_briefing_service_key:
        tasks.append(
            {"key": "policy_briefing", "label": "정책브리핑 API", "category": "auto"}
        )
        coros.append(
            asyncio.to_thread(
                fetch_policy_briefing,
                policy_briefing_service_key,
                "",
                max_records,
                report_date,
            )
        )
    for query in queries:
        query_id = str(query.get("id") or "direct")
        label = str(query.get("label") or query_id or "검색식")
        query_limit = query_max_records(query, max_records)
        if naver_configured:
            naver_queries = [
                str(value).strip()
                for value in (query.get("naverQueries") or [])[:3]
                if str(value).strip()
            ]
            for index, naver_query in enumerate(naver_queries):
                tasks.append(
                    {
                        "key": f"naver:{query_id}:{index}",
                        "label": f"{label} · 네이버 {index + 1}",
                        "category": query_id,
                        "provider": NAVER_PROVIDER,
                        "optional_failure": True,
                    }
                )
                coros.append(
                    asyncio.to_thread(
                        fetch_naver_query,
                        naver_query,
                        naver_client_id,
                        naver_client_secret,
                        within_lookback,
                        query_limit,
                    )
                )
        tasks.append(
            {"key": f"query:{query_id}", "label": label, "category": query_id}
        )
        coros.append(
            asyncio.to_thread(
                fetch_query,
                query,
                endpoint,
                lookback_hours,
                query_limit,
            )
        )

    results = await asyncio.gather(*coros, return_exceptions=True) if coros else []

    collected: list[Article] = []
    providers: list[str] = []
    failures: list[str] = []
    warnings: list[str] = []
    provider_tasks: list[dict[str, Any]] = []

    naver_had_error = False
    for task, result in zip(tasks, results):
        label = task["label"]
        category = task["category"]
        query_group_id = None if category == "auto" else category
        if isinstance(result, BaseException):
            error_message = friendly_error(result)
            if task.get("optional_failure"):
                naver_had_error = True
                warnings.append(f"{label}: 네이버 뉴스 API 오류({error_message})")
            else:
                failures.append(f"{label}: {error_message}")
            provider_tasks.append(
                {
                    "key": task["key"],
                    "label": label,
                    "provider": task.get("provider") or label,
                    "query_group_id": query_group_id,
                    "status": "failed",
                    "raw_count": 0,
                    "error_message": error_message,
                }
            )
            continue
        items = result["items"]
        for item in items:
            assigned_category = infer_category(item)
            collected.append(
                {
                    **item,
                    "category": assigned_category,
                    "_task_label": label,
                    "_task_key": task["key"],
                    "_query_group_id": query_group_id,
                }
            )
        provider_label = result.get("provider")
        if provider_label and provider_label not in providers:
            providers.append(provider_label)
        warning = result.get("warning")
        if warning:
            warnings.append(f"{label}: {warning}")
        provider_tasks.append(
            {
                "key": task["key"],
                "label": label,
                "provider": provider_label,
                "query_group_id": query_group_id,
                "status": "success",
                "raw_count": len(items),
                "warning_message": warning,
            }
        )

    network_succeeded = bool(providers)
    if enable_media_fallback and not collected and failures:
        try:
            gdelt_items = await asyncio.to_thread(fetch_gdelt_combined, core_keywords, lookback_hours, max_records)
            for item in gdelt_items:
                collected.append(
                    {
                        **item,
                        "category": infer_category(item),
                        "_task_label": "GDELT",
                        "_task_key": "gdelt",
                        "_query_group_id": None,
                    }
                )
            if "GDELT" not in providers:
                providers.append("GDELT")
            network_succeeded = True
            warnings.extend(f"RSS 보조 전환: {f}" for f in failures)
            provider_tasks.append(
                {
                    "key": "gdelt",
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
                    "key": "gdelt",
                    "label": "GDELT",
                    "provider": "GDELT",
                    "query_group_id": None,
                    "status": "failed",
                    "raw_count": 0,
                    "error_message": friendly_error(gdelt_error),
                }
            )

    source_filtered, source_filter_stats = filter_trusted_sources(collected)
    sentinel_checked = [
        {**article, "_sentinel": article.get("_sentinel") or detect_incident_sentinel(article)}
        for article in source_filtered
    ]
    relevant = [
        article
        for article in sentinel_checked
        if article.get("_official_government") is True
        or article["_sentinel"]["matched"]
        or get_relevance(article)["rank"] < 99
    ]
    eligible = [
        article
        for article in relevant
        if (
            article.get("_official_government") is True
            or not should_exclude(article, exclude_keywords)
        )
        and within_lookback(article)
    ]
    first_pass_items, duplicates_removed = deduplicate_detailed(eligible, risk_keywords, positive_keywords)

    classified_items = [classify_article(raw, risk_keywords, positive_keywords) for raw in first_pass_items]
    classified_items.sort(key=relevance_sort_key)
    classified_items = apply_collection_limit(classified_items, collection_limit)

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
                    source_filter_stats=source_filter_stats,
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
                    "source_filter_stats": source_filter_stats,
                    "naverStatus": "네이버 뉴스 API 오류"
                    if naver_had_error
                    else (
                        "네이버 뉴스 API 연결됨"
                        if naver_configured
                        else "네이버 뉴스 API 미설정"
                    ),
                }

            new_count = 0
            matched_count = 0
            origin_matched_count = 0
            origin_releases = press_release_repo.list_recent(connection)
            for item in classified_items:
                article_id, dedup_method, matched = _upsert_article_for_item(connection, item)
                if matched:
                    matched_count += 1
                else:
                    new_count += 1
                observations = item.get("_observations") or [item]
                representative_url = canonical_article_url(item.get("url"))
                for index, observation in enumerate(observations):
                    observation_url = canonical_article_url(observation.get("url"))
                    observation_method = dedup_method
                    if index > 0:
                        observation_method = (
                            "canonical_url"
                            if representative_url
                            and observation_url
                            and representative_url == observation_url
                            else "fuzzy_same_copy"
                        )
                    article_repo.insert_observation(
                        connection,
                        article_id=article_id,
                        collection_run_provider_id=provider_id_by_label.get(
                            observation.get("_task_key")
                        ),
                        provider=observation.get("provider")
                        or observation.get("_task_label")
                        or "unknown",
                        provider_item_key=observation.get("sourceId"),
                        query_group_id=observation.get("_query_group_id"),
                        raw_url=observation.get("url"),
                        raw_title=observation.get("title"),
                        raw_source=observation.get("source"),
                        raw_published_at=observation.get("pubDate"),
                        raw_description=observation.get("description"),
                        raw_payload_json=None,
                        dedup_method=observation_method,
                        dedup_score=None,
                    )
                article_repo.upsert_assessment(
                    connection,
                    article_id=article_id,
                    assessment={**item["assessment"], "autoCategory": item.get("category")},
                    classifier_version=CLASSIFIER_VERSION,
                )
                origin = assess_kesco_origin(item, origin_releases)
                if origin:
                    press_release_repo.upsert_origin(
                        connection,
                        article_id,
                        origin,
                        ORIGIN_CLASSIFIER_VERSION,
                    )
                    origin_matched_count += 1

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
                source_filter_stats=source_filter_stats,
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
        "kescoPressReleaseCount": len(origin_releases),
        "kescoPressMatchedCount": origin_matched_count,
        "duplicatesRemoved": duplicates_removed,
        "fetchedAt": finished_at,
        "errors": [],
        "warnings": [*warnings, *(f"일부 검색 실패: {f}" for f in failures)],
        "collectionRunId": run_id,
        "source_filter_stats": source_filter_stats,
        "naverStatus": "네이버 뉴스 API 오류"
        if naver_had_error
        else (
            "네이버 뉴스 API 연결됨"
            if naver_configured
            else "네이버 뉴스 API 미설정"
        ),
    }
