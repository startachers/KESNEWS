from backend.app.services.deduplication.fuzzy import bigram_similarity
from backend.app.services.deduplication.service import (
    deduplicate_detailed,
    merge_duplicate_articles,
    same_article,
)

RISK_KEYWORDS = ["화재", "감전", "사고"]
POSITIVE_KEYWORDS = ["캠페인"]


def _article(**overrides):
    base = {
        "title": "한국전기안전공사 전기화재 예방 캠페인 실시",
        "source": "연합뉴스",
        "url": "https://www.yna.co.kr/view/AKR20260715000001",
        "pubDate": "2026-07-15T09:00:00Z",
        "description": "여름철 전기화재를 예방하기 위한 캠페인을 실시한다.",
        "provider": "연합뉴스 RSS",
    }
    base.update(overrides)
    return base


def test_same_article_matches_on_canonical_url():
    a = _article()
    b = _article(title="전혀 다른 제목이지만 URL은 같음", url=a["url"] + "?utm_source=rss")
    assert same_article(a, b) is True


def test_same_article_matches_on_fuzzy_title_within_window():
    a = _article(url="https://a.example.com/1")
    b = _article(url="https://b.example.com/2", title="한국전기안전공사 전기화재예방 캠페인을 실시")
    assert same_article(a, b) is True


def test_same_article_rejects_when_pubdate_too_far_apart():
    # 제목을 완전히 동일하게 두면 title 완전일치 분기에서 날짜 확인 없이 True가 되므로,
    # fuzzy 일치(완전동일은 아님)로 유도해 72시간 초과 시 거부되는 경로를 검증한다.
    a = _article(url="https://a.example.com/1")
    b = _article(
        url="https://b.example.com/2",
        title="한국전기안전공사 전기화재 예방 캠페인을 실시",
        pubDate="2026-07-10T09:00:00Z",
    )
    assert same_article(a, b) is False


def test_same_article_rejects_unrelated_titles():
    a = _article(url="https://a.example.com/1")
    b = _article(url="https://b.example.com/2", title="오늘의 날씨 전국 대체로 맑음")
    assert same_article(a, b) is False


def test_bigram_similarity_identical_strings_is_one():
    assert bigram_similarity("전기화재예방", "전기화재예방") == 1.0


def test_merge_duplicate_articles_unions_matched_keywords_and_or_flags():
    left = {
        **_article(),
        "included": True,
        "starred": False,
        "note": "담당자 메모",
        "matchedKeywords": ["화재"],
        "manual": False,
    }
    right = {
        **_article(url="https://other.example.com/1"),
        "included": False,
        "starred": True,
        "note": "",
        "matchedKeywords": ["캠페인"],
        "manual": True,
    }
    merged = merge_duplicate_articles(left, right)
    assert merged["included"] is True
    assert merged["starred"] is True
    assert merged["note"] == "담당자 메모"
    assert set(merged["matchedKeywords"]) == {"화재", "캠페인"}
    # manual 기사가 preference를 갖는다(article_preference에서 manual 가중치가 가장 큼).
    assert merged["manual"] is True


def test_deduplicate_detailed_merges_cross_provider_duplicates():
    items = [
        _article(provider="연합뉴스 RSS"),
        _article(provider="Google 뉴스 RSS", url="https://news.google.com/rss/articles/x"),
        _article(title="오늘의 날씨 전국 대체로 맑음", url="https://other.example.com/weather"),
    ]
    unique, removed = deduplicate_detailed(items, RISK_KEYWORDS, POSITIVE_KEYWORDS)
    assert removed == 1
    assert len(unique) == 2
