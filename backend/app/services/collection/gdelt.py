from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

from backend.app.services.collection.http import CollectionHttpError, http_get
from backend.app.services.extraction.cleaner import clean_text, short_text
from backend.app.services.ids import make_id
from backend.app.services.normalization.dates import parse_gdelt_date

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"


def fetch_gdelt_combined(
    core_keywords: list[str], lookback_hours: int, max_records: int
) -> list[dict[str, Any]]:
    terms = " OR ".join(f'"{term.replace(chr(34), "")}"' for term in core_keywords if term)
    query = f"({terms}) sourcelang:korean"
    limit = min(100, max(20, max_records * 3))
    url = (
        f"{GDELT_URL}?query={quote(query, safe='')}&mode=artlist&maxrecords={limit}"
        f"&format=json&timespan={lookback_hours}h&sort=datedesc"
    )
    status, text = http_get(url, {"Accept": "application/json"}, 18)
    if not (200 <= status < 300):
        detail = short_text(text, 140)
        if status == 429:
            raise CollectionHttpError(f"GDELT 속도 제한(429): {detail or '잠시 후 다시 시도해 주세요.'}", status=429)
        raise CollectionHttpError(f"GDELT 응답 {status}: {detail}", status=status)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CollectionHttpError(f"GDELT 응답 형식 오류: {short_text(text, 140)}") from exc

    result = []
    for item in data.get("articles") or []:
        result.append(
            {
                "id": make_id(),
                "title": clean_text(item.get("title") or "제목 없음"),
                "source": clean_text(item.get("domain") or "출처 미상"),
                "url": item.get("url") or "",
                "pubDate": parse_gdelt_date(item.get("seendate")),
                "description": clean_text("" if item.get("socialimage") else (item.get("snippet") or "")),
                "provider": "GDELT",
            }
        )
    return result
