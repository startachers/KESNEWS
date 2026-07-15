from __future__ import annotations

import math
import re
from typing import Any
from urllib.parse import quote

from backend.app.services.collection.http import CollectionHttpError, http_get
from backend.app.services.collection.rss_parser import parse_rss_items

_TRAILING_SOURCE = re.compile(r"\s[-–—]\s([^-–—]{2,30})$")


def _infer_source_from_title(title: str) -> str:
    match = _TRAILING_SOURCE.search(title)
    return match.group(1) if match else "출처 미상"


def fetch_google_rss(query_text: str, lookback_hours: int, max_records: int) -> list[dict[str, Any]]:
    days = max(1, math.ceil(lookback_hours / 24))
    feed_url = (
        "https://news.google.com/rss/search?"
        f"q={quote(f'{query_text} when:{days}d', safe='')}&hl=ko&gl=KR&ceid=KR:ko"
    )
    status, text = http_get(feed_url, {"Accept": "application/rss+xml, application/xml, text/xml, */*"}, 16)
    if not (200 <= status < 300):
        raise CollectionHttpError(f"Google 뉴스 RSS 응답 {status}", status=status)

    items = parse_rss_items(text, "Google 뉴스 RSS")[:max_records]
    result = []
    for item in items:
        source = item.get("source")
        title = item["title"]
        if source and title.endswith(f" - {source}"):
            title = title[: -(len(source) + 3)].strip()
        result.append({**item, "title": title, "source": source or _infer_source_from_title(title)})
    return result
