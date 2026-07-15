from __future__ import annotations

from typing import Any, Callable

from backend.app.services.classification.service import get_relevance
from backend.app.services.collection.http import CollectionHttpError, http_get
from backend.app.services.collection.rss_parser import parse_rss_items

FEED_URL = "https://www.yna.co.kr/rss/news.xml"


def fetch_yonhap_rss(
    within_lookback: Callable[[str | None], bool], collection_limit: int
) -> dict[str, Any]:
    status, text = http_get(FEED_URL, {"Accept": "application/rss+xml, application/xml, text/xml, */*"}, 16)
    if not (200 <= status < 300):
        raise CollectionHttpError(f"연합뉴스 RSS 응답 {status}", status=status)
    items = parse_rss_items(text, "연합뉴스 RSS", "연합뉴스")
    items = [item for item in items if within_lookback(item.get("pubDate"))]
    items = [item for item in items if get_relevance(item)["rank"] < 99]
    return {"items": items[:collection_limit], "provider": "연합뉴스 RSS"}
