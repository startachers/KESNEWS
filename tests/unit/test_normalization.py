from backend.app.services.extraction.cleaner import clean_text
from backend.app.services.normalization.dates import date_value, parse_date, parse_gdelt_date
from backend.app.services.normalization.title import normalized_article_title
from backend.app.services.normalization.url import canonical_article_url


def test_clean_text_strips_tags_and_collapses_whitespace():
    assert clean_text("<b>화재</b>  발생\n현장") == "화재 발생 현장"
    assert clean_text(None) == ""


def test_clean_text_decodes_entities():
    assert clean_text("한국전기안전공사&nbsp;소식") == "한국전기안전공사 소식"


def test_normalized_article_title_strips_brackets_and_source_suffix():
    assert normalized_article_title("[단독] 전기화재 예방 캠페인 - 연합뉴스") == "전기화재예방캠페인"


def test_normalized_article_title_handles_empty():
    assert normalized_article_title("") == ""
    assert normalized_article_title(None) == ""


def test_canonical_article_url_returns_empty_for_google_news_redirect():
    # LEG-011: Google 뉴스 중계 URL은 원문 URL을 알 수 없으므로 canonical URL을 비워 제목 기반 dedup에 맡긴다.
    assert canonical_article_url("https://news.google.com/rss/articles/CBMi123?oc=5") == ""


def test_canonical_article_url_strips_tracking_params_and_www():
    left = canonical_article_url("https://www.yna.co.kr/view/AKR20260715000001?utm_source=rss&utm_medium=feed")
    right = canonical_article_url("https://yna.co.kr/view/AKR20260715000001")
    assert left == right == "yna.co.kr/view/akr20260715000001"


def test_canonical_article_url_invalid_returns_empty():
    assert canonical_article_url("") == ""
    assert canonical_article_url("not a url") == ""


def test_parse_date_handles_rfc822_and_iso():
    assert parse_date("Wed, 15 Jul 2026 09:00:00 GMT") == "2026-07-15T09:00:00Z"
    assert parse_date("2026-07-15T09:00:00Z") == "2026-07-15T09:00:00Z"
    assert parse_date(None).endswith("Z")


def test_parse_gdelt_date_converts_compact_format():
    assert parse_gdelt_date("20260715T090000Z") == "2026-07-15T09:00:00Z"


def test_date_value_orders_correctly():
    assert date_value("2026-07-15T09:00:00Z") > date_value("2026-07-15T08:00:00Z")
    assert date_value(None) == 0
