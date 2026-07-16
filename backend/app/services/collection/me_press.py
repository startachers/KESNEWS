from __future__ import annotations

import re
from html import unescape
from typing import Any
from urllib.parse import urlencode

from backend.app.services.collection.http import CollectionHttpError, http_get
from backend.app.services.extraction.cleaner import clean_text
from backend.app.services.ids import make_id
from backend.app.services.normalization.dates import parse_date

LIST_URL = "https://me.go.kr/home/web/board/list.do"
DETAIL_URL = "https://me.go.kr/home/web/board/read.do"
# 2026-07-16 실측 확인: 보도자료 게시판(boardMasterId=939)의 메뉴 ID.
BOARD_MASTER_ID = "939"
MENU_ID = "10598"
PROVIDER = "기후에너지환경부 보도자료"

_ROW_RE = re.compile(r"<tr\b.*?</tr>", re.DOTALL)
_TITLE_RE = re.compile(
    r'<a[^>]+href="([^"]*boardId=(\d+)[^"]*)"[^>]*class="ellipsis"[^>]*>(.*?)</a>',
    re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")
_JSESSIONID_RE = re.compile(r";jsessionid=[^?]*")
_DATE_RE = re.compile(r"^\d{4}[.\-]\d{2}[.\-]\d{2}$")


def _plain_text(fragment: str) -> str:
    return clean_text(_TAG_RE.sub(" ", fragment))


def _canonical_detail_url(href: str) -> str:
    href = _JSESSIONID_RE.sub("", unescape(href))
    query = href.split("?", 1)[1] if "?" in href else ""
    return f"{DETAIL_URL}?{query}" if query else DETAIL_URL


def _parse_rows(html: str) -> list[dict[str, Any]]:
    """me.go.kr 보도자료 목록 표(2026-07-16 실측)를 정규식으로 읽는다: <tr>마다 제목 링크의
    boardId와 뒤이은 <td>부서명</td><td>등록자명</td><td>등록일자</td> 컬럼 순서에 의존한다."""
    items: list[dict[str, Any]] = []
    for row_html in _ROW_RE.findall(html):
        title_match = _TITLE_RE.search(row_html)
        if not title_match:
            continue
        href, board_id, raw_title = title_match.groups()
        title = _plain_text(raw_title)
        if not title:
            continue
        tds = [_plain_text(td) for td in re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.DOTALL)]
        plain_tds = [t for t in tds if t]
        department = plain_tds[2] if len(plain_tds) > 2 else ""
        raw_date = next((t for t in plain_tds if _DATE_RE.match(t)), "")
        items.append(
            {
                "id": make_id(),
                "sourceId": f"me:{board_id}",
                "title": title,
                "source": PROVIDER,
                "url": _canonical_detail_url(href),
                "pubDate": parse_date(raw_date.replace(".", "-") if raw_date else None),
                "description": department,
                "provider": PROVIDER,
            }
        )
    return items


def fetch_me_press(max_records: int) -> dict[str, Any]:
    query = urlencode(
        {
            "menuId": MENU_ID,
            "boardMasterId": BOARD_MASTER_ID,
            "maxPageItems": max(max_records, 1),
        }
    )
    status, text = http_get(
        f"{LIST_URL}?{query}",
        {"Accept": "text/html", "User-Agent": "Mozilla/5.0 (compatible; KESCONewsBot/1.0)"},
        16,
    )
    if not (200 <= status < 300):
        raise CollectionHttpError(f"기후에너지환경부 보도자료 응답 {status}", status=status)
    items = _parse_rows(text)[:max_records]
    return {"items": items, "provider": PROVIDER}
