from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote
from xml.etree import ElementTree

from backend.app.core.clock import SEOUL_TZ
from backend.app.services.collection.http import CollectionHttpError, http_get
from backend.app.services.extraction.cleaner import clean_text
from backend.app.services.ids import make_id
from backend.app.services.normalization.dates import parse_date

# 문화체육관광부_정책브리핑_정책뉴스_API (data.go.kr, 서비스ID 1371000/policyNewsService,
# 데이터 15095335). 기존 pressReleaseService(보도자료) 카탈로그는 포털에서 폐지돼 신규
# 활용신청이 불가능하고, 승인 가능한 정책뉴스 API가 같은 필드 스키마를 제공한다.
BASE_URL = "http://apis.data.go.kr/1371000/policyNewsService/policyNewsList"
PROVIDER = "정책브리핑 API"

_TITLE_KEYS = ("Title", "title", "artcTitle", "sj")
_BODY_KEYS = ("DataContents", "content", "bodyCn", "artcContent", "cn")
_DEPT_KEYS = ("MinisterCode", "pDeptNm", "deptNm", "department", "ministry")
_DATE_KEYS = ("ApproveDate", "insertDt", "crtDt", "regDt", "pubDate")
_URL_KEYS = ("OriginalUrl", "orgUrl", "url", "link", "detailUrl")
_ID_KEYS = ("NewsItemId", "dataSeq", "newsId", "id", "artcId")


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


def _extract_xml_items(text: str) -> list[dict[str, Any]]:
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as exc:
        raise CollectionHttpError("정책브리핑 API 응답 형식 오류") from exc
    result_code = next(
        (clean_text(node.text or "") for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "resultCode"),
        "",
    )
    if result_code and result_code not in {"0", "00"}:
        result_message = next(
            (clean_text(node.text or "") for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "resultMsg"),
            "정책브리핑 API 오류",
        )
        raise CollectionHttpError(f"정책브리핑 API 오류({result_code}): {result_message}")
    # 정책뉴스 API는 <body>의 직접 자식으로 <NewsItem>을 반복한다. 과거 pressRelease
    # 계약의 <item>도 계속 허용하도록 지역명이 "item"으로 끝나는 노드를 모두 아이템으로 본다.
    return [
        {child.tag.rsplit("}", 1)[-1]: child.text or "" for child in node}
        for node in root.iter()
        if node.tag.rsplit("}", 1)[-1].lower().endswith("item")
    ]


def _policy_date(value: str) -> str:
    text = clean_text(value)
    for pattern in ("%m/%d/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(text, pattern).replace(tzinfo=SEOUL_TZ)
            return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        except ValueError:
            continue
    return parse_date(text or None)


def _request_dates(report_date: str | None) -> tuple[str, str]:
    try:
        end = date.fromisoformat(report_date or "")
    except ValueError:
        end = datetime.now(SEOUL_TZ).date()
    return (end - timedelta(days=1)).strftime("%Y%m%d"), end.strftime("%Y%m%d")


def fetch_policy_briefing(
    service_key: str,
    query_text: str,
    max_records: int,
    report_date: str | None = None,
) -> dict[str, Any]:
    _ = query_text  # 이전 어댑터 호출 계약을 유지한다. 이 API는 검색어 대신 날짜 범위를 요구한다.
    if not service_key.strip():
        return {"items": [], "provider": PROVIDER}
    start_date, end_date = _request_dates(report_date)
    params = (
        f"?serviceKey={quote(service_key, safe='%')}&startDate={start_date}&endDate={end_date}"
    )
    status, text = http_get(
        f"{BASE_URL}{params}",
        {"Accept": "application/xml, application/json"},
        16,
    )
    if not (200 <= status < 300):
        if status == 403:
            raise CollectionHttpError(
                "공공데이터포털 정책브리핑 API 접근 거부(403): "
                "해당 보도자료 API의 활용신청 승인 상태와 인증키를 확인하세요.",
                status=status,
            )
        if status == 401:
            raise CollectionHttpError(
                "공공데이터포털 정책브리핑 API 인증 실패(401): "
                "설정에 저장된 인증키를 확인하세요.",
                status=status,
            )
        raise CollectionHttpError(f"정책브리핑 API 응답 {status}", status=status)
    stripped = text.lstrip()
    if stripped.startswith(("{", "[")):
        try:
            raw_items = _extract_items(json.loads(text))
        except json.JSONDecodeError as exc:
            raise CollectionHttpError("정책브리핑 API 응답 형식 오류") from exc
    else:
        raw_items = _extract_xml_items(text)

    items: list[dict[str, Any]] = []
    for raw in raw_items[:max_records]:
        title = clean_text(_first(raw, _TITLE_KEYS)) or "제목 없음"
        source_id = _first(raw, _ID_KEYS)
        department = clean_text(_first(raw, _DEPT_KEYS))
        items.append(
            {
                "id": make_id(),
                "sourceId": f"policy-briefing:{source_id}" if source_id else "",
                "title": title,
                "source": department or "정부부처 보도자료",
                "url": _first(raw, _URL_KEYS),
                "pubDate": _policy_date(_first(raw, _DATE_KEYS)),
                "description": clean_text(_first(raw, _BODY_KEYS)) or department,
                "provider": PROVIDER,
            }
        )
    return {"items": items, "provider": PROVIDER}
