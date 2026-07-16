from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

from backend.app.services.collection.http import CollectionHttpError, http_get
from backend.app.services.extraction.cleaner import clean_text
from backend.app.services.ids import make_id
from backend.app.services.normalization.dates import parse_date

# 문화체육관광부_정책브리핑_보도자료_API (data.go.kr, 서비스ID 1371000/pressReleaseService).
# 응답 필드명은 실제 서비스키 발급 후 확인이 필요해, 확인 전까지는 후보 키를 여러 개
# 시도하는 방어적 파싱을 쓴다(backend.app.services.collection.custom_endpoint와 동일 방식).
BASE_URL = "http://apis.data.go.kr/1371000/pressReleaseService/pressReleaseList"
PROVIDER = "정책브리핑 API"

_TITLE_KEYS = ("title", "artcTitle", "sj")
_BODY_KEYS = ("content", "bodyCn", "artcContent", "cn")
_DEPT_KEYS = ("pDeptNm", "deptNm", "department", "ministry")
_DATE_KEYS = ("insertDt", "crtDt", "regDt", "pubDate")
_URL_KEYS = ("orgUrl", "url", "link", "detailUrl")
_ID_KEYS = ("dataSeq", "newsId", "id", "artcId")


def _first(item: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = item.get(key)
        if value:
            return str(value)
    return ""


def _extract_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    body = ((payload.get("response") or {}).get("body")) or payload.get("body") or payload
    raw_items = (body.get("items") or {}) if isinstance(body, dict) else {}
    item_list = raw_items.get("item") if isinstance(raw_items, dict) else raw_items
    if item_list is None:
        item_list = body.get("item") if isinstance(body, dict) else None
    if isinstance(item_list, dict):
        item_list = [item_list]
    return item_list if isinstance(item_list, list) else []


def fetch_policy_briefing(service_key: str, query_text: str, max_records: int) -> dict[str, Any]:
    if not service_key.strip():
        return {"items": [], "provider": PROVIDER}
    params = (
        f"?serviceKey={service_key}&pageNo=1&numOfRows={max(max_records, 1)}&type=json"
        + (f"&srchWrd={quote(query_text, safe='')}" if query_text.strip() else "")
    )
    status, text = http_get(f"{BASE_URL}{params}", {"Accept": "application/json"}, 16)
    if not (200 <= status < 300):
        raise CollectionHttpError(f"정책브리핑 API 응답 {status}", status=status)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CollectionHttpError("정책브리핑 API 응답 형식 오류") from exc

    items: list[dict[str, Any]] = []
    for raw in _extract_items(payload)[:max_records]:
        title = clean_text(_first(raw, _TITLE_KEYS)) or "제목 없음"
        source_id = _first(raw, _ID_KEYS)
        items.append(
            {
                "id": make_id(),
                "sourceId": f"policy-briefing:{source_id}" if source_id else "",
                "title": title,
                "source": PROVIDER,
                "url": _first(raw, _URL_KEYS),
                "pubDate": parse_date(_first(raw, _DATE_KEYS) or None),
                "description": clean_text(_first(raw, _BODY_KEYS)) or _first(raw, _DEPT_KEYS),
                "provider": PROVIDER,
            }
        )
    return {"items": items, "provider": PROVIDER}
