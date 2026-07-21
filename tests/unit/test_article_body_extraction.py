import json
import base64

from backend.app.services.extraction import article_body
from backend.app.services.extraction.article_body import (
    decode_google_news_url,
    decode_html,
    extract_article_body,
    parse_google_news_batch_response,
    fetch_article_body_with_retries,
)


BODY = "한국전기안전공사는 여름철 전기설비 안전점검을 확대한다. " * 8


def test_extracts_schema_org_article_body_before_page_chrome():
    payload = json.dumps({"@type": "NewsArticle", "articleBody": BODY}, ensure_ascii=False)
    html = f"""
    <html><body><nav>메뉴와 광고 문구</nav>
    <script type="application/ld+json">{payload}</script>
    <article><p>짧은 화면 요약입니다.</p></article></body></html>
    """
    assert extract_article_body(html) == BODY.strip()


def test_extracts_semantic_article_and_excludes_navigation():
    html = f"""
    <html><body><header>언론사 메뉴</header><main class="article-content">
    <p>{BODY[:220]}</p><aside>관련 기사 광고</aside><p>{BODY[220:]}</p>
    </main><footer>제보 안내</footer></body></html>
    """
    result = extract_article_body(html)
    assert "한국전기안전공사" in result
    assert "관련 기사 광고" not in result
    assert "제보 안내" not in result


def test_rejects_short_metadata_as_full_article():
    assert extract_article_body("<article><p>짧은 요약입니다.</p></article>") == ""


def test_decodes_legacy_google_news_url(monkeypatch):
    target = "https://example.com/news/full-story"
    payload = b"\x08\x13\x22" + bytes([len(target)]) + target.encode() + b"\xd2\x01\x00"
    token = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    monkeypatch.setattr(article_body, "_validate_public_url", lambda url: None)
    assert decode_google_news_url(f"https://news.google.com/rss/articles/{token}?oc=5") == target


def test_modern_google_news_token_uses_batch_decoder(monkeypatch):
    payload = b"\x08\x13\x22" + bytes([6]) + b"AU_yqL" + b"\xd2\x01\x00"
    token = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    monkeypatch.setattr(
        article_body,
        "_decode_modern_google_news_token",
        lambda value, timeout: "https://publisher.example/article",
    )
    assert decode_google_news_url(f"https://news.google.com/rss/articles/{token}") == (
        "https://publisher.example/article"
    )


def test_google_news_parameter_parser_reads_current_data_attribute():
    parser = article_body._GoogleNewsParamsParser()
    parser.feed('<c-wiz data-p="%.@.[[&quot;en-US&quot;],&quot;TOKEN&quot;]"></c-wiz>')
    assert parser.data_p == '%.@.[["en-US"],"TOKEN"]'


def test_page_metadata_prefers_json_ld_publisher_and_reads_canonical():
    html = '''
    <html><head>
      <link rel="canonical" href="https://www.joongang.co.kr/article/1">
      <meta property="og:site_name" content="다른 표시값">
      <script type="application/ld+json">{"@type":"NewsArticle","publisher":{"name":"중앙일보"}}</script>
    </head></html>
    '''
    canonical, _ = article_body.extract_page_metadata(html, url="https://joongang.co.kr/a")
    assert canonical == "https://www.joongang.co.kr/article/1"
    assert article_body.extract_page_publisher(html, url="https://joongang.co.kr/a") == "중앙일보"


def test_decode_html_recovers_cp949_when_header_claims_utf8():
    text = "에너지공기업 여름철 안전대책과 변압기 설비 점검"
    assert decode_html(text.encode("cp949"), "utf-8") == text


def test_google_batch_response_unescapes_query_delimiters():
    raw = r'[["wrb.fr","Fbv4je","[\"garturlres\",\"https://example.com/a?x\\u003d1\\u0026y\\u003d2\",1]"]]'
    assert parse_google_news_batch_response(raw) == "https://example.com/a?x=1&y=2"


def test_multistage_fetch_retries_mobile_and_records_attempts(monkeypatch):
    monkeypatch.setattr(article_body, "decode_google_news_url", lambda url, timeout: url)
    monkeypatch.setattr(
        article_body,
        "alternate_urls",
        lambda url: [("mobile", "https://m.example.com/story")],
    )

    def fake_fetch(url, timeout):
        if "m.example" not in url:
            raise ValueError("첫 페이지 실패")
        return f"<article><p>{BODY * 3}</p></article>", url, ""

    monkeypatch.setattr(article_body, "_fetch_page", fake_fetch)
    result = fetch_article_body_with_retries("https://example.com/story")
    assert result.status == "success_full"
    assert result.resolved_url == "https://m.example.com/story"
    assert [attempt["stage"] for attempt in result.attempts] == ["original", "mobile"]


def test_multistage_fetch_uses_meta_description_only_as_summary(monkeypatch):
    summary = "7월 20일 공사는 전기설비 안전점검 계획과 대상, 현장 일정 및 관계기관 협력 방안을 발표했다고 밝혔다. " * 2
    monkeypatch.setattr(article_body, "decode_google_news_url", lambda url, timeout: url)
    monkeypatch.setattr(article_body, "alternate_urls", lambda url: [])
    monkeypatch.setattr(article_body, "_fetch_page", lambda url, timeout: ("<html></html>", url, summary))
    result = fetch_article_body_with_retries("https://example.com/story")
    assert result.status == "success_summary"
    assert result.body_text == summary


def test_multistage_fetch_continues_when_first_body_fails_quality(monkeypatch):
    short_body = "메뉴와 추천 기사뿐인 본문 " * 20
    full_body = BODY * 4
    monkeypatch.setattr(article_body, "decode_google_news_url", lambda url, timeout: url)
    monkeypatch.setattr(article_body, "alternate_urls", lambda url: [("amp", f"{url}/amp")])
    monkeypatch.setattr(
        article_body,
        "_fetch_page",
        lambda url, timeout: (
            f"<article><p>{full_body if url.endswith('/amp') else short_body}</p></article>", url, ""
        ),
    )
    result = fetch_article_body_with_retries(
        "https://example.com/story", body_validator=lambda body, url: len(body) >= 500
    )
    assert result.status == "success_full"
    assert result.body_text == full_body.strip()
    assert [attempt["status"] for attempt in result.attempts] == ["quality_failed", "success"]
