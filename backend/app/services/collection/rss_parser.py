from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

from backend.app.services.extraction.cleaner import clean_text
from backend.app.services.ids import make_id
from backend.app.services.normalization.dates import parse_date

_DC_DATE = "{http://purl.org/dc/elements/1.1/}date"


class RssParseError(Exception):
    pass


def _text(item: ET.Element, tag: str) -> str:
    value = item.findtext(tag)
    return value if value else ""


def parse_rss_items(text: str, provider: str, default_source: str = "") -> list[dict[str, Any]]:
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise RssParseError("RSS 형식을 읽을 수 없습니다.") from exc

    result: list[dict[str, Any]] = []
    for item in root.findall(".//item"):
        source_element = item.find("source")
        source = clean_text(source_element.text if source_element is not None else "")
        source_url = clean_text(source_element.get("url", "") if source_element is not None else "")
        date_text = item.findtext("pubDate") or item.findtext(_DC_DATE)
        result.append(
            {
                "id": make_id(),
                "title": clean_text(_text(item, "title")) or "제목 없음",
                "source": source or default_source,
                "sourceUrl": source_url,
                "url": clean_text(_text(item, "link")),
                "pubDate": parse_date(date_text),
                "description": clean_text(_text(item, "description")),
                "provider": provider,
            }
        )
    return result
