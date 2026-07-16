from __future__ import annotations

import math
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from typing import Any

from backend.app.core.clock import now_iso
from backend.app.services.collection.http import CollectionHttpError, http_get
from backend.app.services.extraction.cleaner import clean_text
from backend.app.services.normalization.dates import parse_date

LIST_URL = "https://www.kesco.or.kr/bbs/pr/selectPageListBbs.do?bbs_code=MKB00002"
DETAIL_URL = "https://www.kesco.or.kr/bbs/pr/selectBbs.do?bbs_code=MKB00002&bbs_seq={bbs_seq}"
PROVIDER = "한국전기안전공사 보도자료"
PAGE_SIZE = 10

_ROW_RE = re.compile(r"<tr\b.*?</tr>", re.DOTALL)
_SEQ_TITLE_RE = re.compile(
    r"fnDetail\('(?P<seq>\d+)'[^)]*\).*?>(?P<title>.*?)</a>", re.DOTALL
)
_DATE_RE = re.compile(r"\d{4}[.]\d{2}[.]\d{2}")
_TAG_RE = re.compile(r"<[^>]+>")


class _DetailParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_title = False
        self.content_depth = 0
        self.title_parts: list[str] = []
        self.content_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        classes = set((values.get("class") or "").split())
        if tag == "h4" and "tit1" in classes:
            self.in_title = True
        if tag == "div" and values.get("id") == "cn":
            self.content_depth = 1
        elif tag == "div" and self.content_depth:
            self.content_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "h4" and self.in_title:
            self.in_title = False
        if tag == "div" and self.content_depth:
            self.content_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data)
        if self.content_depth:
            self.content_parts.append(data)


def _parse_list(html: str) -> list[dict[str, Any]]:
    items = []
    for row in _ROW_RE.findall(html):
        match = _SEQ_TITLE_RE.search(row)
        if not match:
            continue
        title = clean_text(_TAG_RE.sub(" ", match.group("title")))
        date_match = _DATE_RE.search(row)
        if not title or not date_match:
            continue
        bbs_seq = match.group("seq")
        items.append(
            {
                "id": f"kesco:{bbs_seq}",
                "bbsSeq": bbs_seq,
                "title": title,
                "publishedAt": parse_date(date_match.group(0).replace(".", "-")),
                "url": DETAIL_URL.format(bbs_seq=bbs_seq),
            }
        )
    return items


def _parse_detail(html: str) -> tuple[str, str]:
    parser = _DetailParser()
    parser.feed(html)
    parser.close()
    return clean_text(" ".join(parser.title_parts)), clean_text(" ".join(parser.content_parts))


def _fetch_detail(item: dict[str, Any]) -> dict[str, Any]:
    status, html = http_get(
        item["url"],
        {"Accept": "text/html", "User-Agent": "Mozilla/5.0 (compatible; KESCONewsBot/1.0)"},
        16,
    )
    if not (200 <= status < 300):
        raise CollectionHttpError(f"KESCO 보도자료 상세 응답 {status}", status=status)
    title, body = _parse_detail(html)
    return {
        **item,
        "title": title or item["title"],
        "bodyText": body,
        "fetchedAt": now_iso(),
    }


def fetch_kesco_press(max_records: int = 20) -> dict[str, Any]:
    summaries: list[dict[str, Any]] = []
    for page in range(1, max(1, math.ceil(max_records / PAGE_SIZE)) + 1):
        status, html = http_get(
            f"{LIST_URL}&currentPage={page}",
            {"Accept": "text/html", "User-Agent": "Mozilla/5.0 (compatible; KESCONewsBot/1.0)"},
            16,
        )
        if not (200 <= status < 300):
            raise CollectionHttpError(f"KESCO 보도자료 목록 응답 {status}", status=status)
        summaries.extend(_parse_list(html))
        if len(summaries) >= max_records:
            break
    summaries = summaries[:max_records]
    releases: list[dict[str, Any]] = []
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=min(5, len(summaries) or 1)) as executor:
        futures = {executor.submit(_fetch_detail, item): item for item in summaries}
        for future in as_completed(futures):
            try:
                releases.append(future.result())
            except Exception as exc:  # 개별 과거 게시물 오류가 기준 원문 전체를 막지 않는다.
                item = futures[future]
                errors.append(f"{item['bbsSeq']}: {clean_text(str(exc)) or '상세 수집 실패'}")
                releases.append({**item, "bodyText": "", "fetchedAt": now_iso()})
    releases.sort(key=lambda item: (item.get("publishedAt") or "", item["bbsSeq"]), reverse=True)
    return {
        "pressReleases": releases,
        "provider": PROVIDER,
        "warning": f"상세 본문 {len(errors)}건 수집 실패" if errors else None,
    }
