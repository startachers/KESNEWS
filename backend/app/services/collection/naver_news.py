from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode, urlsplit

from backend.app.services.collection.http import CollectionHttpError, http_get
from backend.app.services.extraction.cleaner import clean_text
from backend.app.services.normalization.dates import parse_date

NAVER_NEWS_URL = "https://openapi.naver.com/v1/search/news.json"
NAVER_PROVIDER = "네이버 뉴스 API"
DISPLAY = 100
MAX_PAGES = 3
REQUEST_INTERVAL_SECONDS = 0.25
MAX_RATE_LIMIT_RETRIES = 2
_request_lock = threading.Lock()
_next_request_at = 0.0


def _wait_for_request_slot() -> None:
    """여러 검색군이 병렬 실행돼도 네이버 HTTP 요청 시작 간격을 전역으로 제한한다."""
    global _next_request_at
    with _request_lock:
        now = time.monotonic()
        delay = max(0.0, _next_request_at - now)
        if delay:
            time.sleep(delay)
        _next_request_at = time.monotonic() + REQUEST_INTERVAL_SECONDS


def _defer_requests(seconds: float) -> None:
    global _next_request_at
    with _request_lock:
        _next_request_at = max(_next_request_at, time.monotonic() + seconds)


def normalize_naver_item(item: dict[str, Any]) -> dict[str, Any]:
    original_link = str(item.get("originallink") or "").strip()
    naver_url = str(item.get("link") or "").strip()
    url = original_link or naver_url
    try:
        source = (urlsplit(original_link).hostname or "").removeprefix("www.")
    except ValueError:
        source = ""
    return {
        "title": clean_text(str(item.get("title") or "")),
        "url": url,
        "naverUrl": naver_url,
        "originalLink": original_link,
        "pubDate": parse_date(str(item.get("pubDate") or "")),
        "description": clean_text(str(item.get("description") or "")),
        "source": source or "출처 미상",
        "provider": NAVER_PROVIDER,
    }


def fetch_naver_news(
    query_text: str,
    client_id: str,
    client_secret: str,
    within_lookback: Callable[[str | None], bool],
    *,
    max_pages: int = MAX_PAGES,
) -> list[dict[str, Any]]:
    headers = {
        "Accept": "application/json",
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret,
    }
    collected: list[dict[str, Any]] = []
    for page in range(max(1, min(MAX_PAGES, max_pages))):
        params = urlencode(
            {"query": query_text, "display": DISPLAY, "start": page * DISPLAY + 1, "sort": "date"}
        )
        url = f"{NAVER_NEWS_URL}?{params}"
        status = 0
        text = ""
        for retry in range(MAX_RATE_LIMIT_RETRIES + 1):
            _wait_for_request_slot()
            status, text = http_get(url, headers, 15)
            if status != 429 or retry == MAX_RATE_LIMIT_RETRIES:
                break
            _defer_requests(0.75 * (retry + 1))
        if not (200 <= status < 300):
            raise CollectionHttpError(f"네이버 뉴스 API 응답 {status}", status=status)
        try:
            payload = json.loads(text)
        except (TypeError, json.JSONDecodeError) as exc:
            raise CollectionHttpError("네이버 뉴스 API 응답 형식이 올바르지 않습니다.") from exc
        raw_items = payload.get("items")
        if not isinstance(raw_items, list):
            raise CollectionHttpError("네이버 뉴스 API 응답 형식이 올바르지 않습니다.")

        reached_boundary = False
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                continue
            item = normalize_naver_item(raw_item)
            if within_lookback(item.get("pubDate")):
                if item["url"] and item["title"]:
                    collected.append(item)
            else:
                reached_boundary = True
        if reached_boundary or len(raw_items) < DISPLAY:
            break
    return collected
