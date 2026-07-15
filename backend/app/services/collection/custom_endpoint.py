from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

from backend.app.services.collection.http import CollectionHttpError, http_get
from backend.app.services.extraction.cleaner import clean_text
from backend.app.services.ids import make_id
from backend.app.services.normalization.dates import parse_date


def fetch_custom_endpoint(
    endpoint_template: str, query_text: str, lookback_hours: int, max_records: int
) -> list[dict[str, Any]]:
    endpoint = (
        endpoint_template.strip()
        .replace("{query}", quote(query_text, safe=""))
        .replace("{hours}", quote(str(lookback_hours), safe=""))
        .replace("{limit}", quote(str(max_records), safe=""))
    )
    status, text = http_get(endpoint, {"Accept": "application/json"}, 16)
    if not (200 <= status < 300):
        raise CollectionHttpError(f"기관 API 응답 {status}", status=status)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CollectionHttpError("기관 API 응답 형식 오류") from exc
    items = data if isinstance(data, list) else (data.get("items") or data.get("articles") or [])

    result = []
    for item in items[:max_records]:
        source = item.get("source")
        source_name = source.get("name") if isinstance(source, dict) else source
        result.append(
            {
                "id": make_id(),
                "title": clean_text(item.get("title") or item.get("headline") or "제목 없음"),
                "source": clean_text(source_name or item.get("publisher") or item.get("domain") or "출처 미상"),
                "url": item.get("originallink") or item.get("url") or item.get("link") or "",
                "pubDate": parse_date(
                    item.get("pubDate") or item.get("publishedAt") or item.get("seendate") or item.get("date")
                ),
                "description": clean_text(
                    item.get("description") or item.get("summary") or item.get("snippet") or ""
                ),
                "provider": "기관용 뉴스 API",
            }
        )
    return result
