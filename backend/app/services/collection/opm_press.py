from __future__ import annotations

import re
from typing import Any

from backend.app.services.collection.http import CollectionHttpError, http_get
from backend.app.services.extraction.cleaner import clean_text
from backend.app.services.ids import make_id
from backend.app.services.normalization.dates import parse_date

LIST_URL = "https://www.opm.go.kr/opm/news/press-release.do"
DETAIL_URL = "https://www.opm.go.kr/opm/news/press-release.do?mode=view&articleNo={article_no}"
PROVIDER = "국무조정실 보도자료"

_ROW_RE = re.compile(r"<tr\b.*?</tr>", re.DOTALL)
_TITLE_RE = re.compile(
    r'<a[^>]+href="\?mode=view&amp;articleNo=(\d+)[^"]*"[^>]*class="c-board-title"[^>]*>(.*?)</a>',
    re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")
_DATE_RE = re.compile(r"^\d{4}[.\-]\d{2}[.\-]\d{2}$")


def _plain_text(fragment: str) -> str:
    return clean_text(_TAG_RE.sub(" ", fragment))


def _parse_rows(html: str) -> list[dict[str, Any]]:
    """opm.go.kr 목록 표(2026-07-16 실측)를 정규식으로 읽는다: <tr>마다 제목 링크의
    articleNo와 뒤이은 <td>부서명</td><td>등록일</td> 컬럼 순서에 의존한다."""
    items: list[dict[str, Any]] = []
    for row_html in _ROW_RE.findall(html):
        title_match = _TITLE_RE.search(row_html)
        if not title_match:
            continue
        article_no = title_match.group(1)
        title = _plain_text(title_match.group(2))
        if not title:
            continue
        tds = [_plain_text(td) for td in re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.DOTALL)]
        plain_tds = [t for t in tds if t]
        department = plain_tds[2] if len(plain_tds) > 2 else ""
        raw_date = next((t for t in plain_tds if _DATE_RE.match(t)), "")
        items.append(
            {
                "id": make_id(),
                "sourceId": f"opm:{article_no}",
                "title": title,
                "source": PROVIDER,
                "url": DETAIL_URL.format(article_no=article_no),
                "pubDate": parse_date(raw_date.replace(".", "-") if raw_date else None),
                "description": department,
                "provider": PROVIDER,
            }
        )
    return items


def fetch_opm_press(max_records: int) -> dict[str, Any]:
    status, text = http_get(
        f"{LIST_URL}?mode=list&articleLimit={max(max_records, 1)}&article.offset=0",
        {"Accept": "text/html", "User-Agent": "Mozilla/5.0 (compatible; KESCONewsBot/1.0)"},
        16,
    )
    if not (200 <= status < 300):
        raise CollectionHttpError(f"국무조정실 보도자료 응답 {status}", status=status)
    items = _parse_rows(text)[:max_records]
    return {"items": items, "provider": PROVIDER}
