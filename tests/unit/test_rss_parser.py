from pathlib import Path

import pytest

from backend.app.services.collection.rss_parser import RssParseError, parse_rss_items

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "rss"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_rss_items_extracts_google_news_items():
    items = parse_rss_items(_read("google_news_sample.xml"), "Google 뉴스 RSS")
    assert len(items) == 2
    first = items[0]
    assert first["title"] == "한국전기안전공사, 전기화재 예방 캠페인 실시 - 연합뉴스"
    assert first["source"] == "연합뉴스"
    assert first["provider"] == "Google 뉴스 RSS"
    assert first["pubDate"] == "2026-07-15T09:00:00Z"
    # source 태그가 없는 두 번째 아이템은 default_source로 채워지지 않고 빈 문자열이다(호출부에서 별도 추론).
    assert items[1]["source"] == ""


def test_parse_rss_items_uses_default_source_for_yonhap_feed():
    items = parse_rss_items(_read("yonhap_sample.xml"), "연합뉴스 RSS", "연합뉴스")
    assert len(items) == 2
    assert all(item["source"] == "연합뉴스" for item in items)
    assert all(item["provider"] == "연합뉴스 RSS" for item in items)


def test_parse_rss_items_raises_on_malformed_xml():
    with pytest.raises(RssParseError):
        parse_rss_items(_read("malformed.xml"), "연합뉴스 RSS")
