import json
import base64

from backend.app.services.extraction import article_body
from backend.app.services.extraction.article_body import (
    decode_google_news_url,
    decode_html,
    extract_article_body,
    parse_google_news_batch_response,
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


def test_decode_html_recovers_cp949_when_header_claims_utf8():
    text = "에너지공기업 여름철 안전대책과 변압기 설비 점검"
    assert decode_html(text.encode("cp949"), "utf-8") == text


def test_google_batch_response_unescapes_query_delimiters():
    raw = r'[["wrb.fr","Fbv4je","[\"garturlres\",\"https://example.com/a?x\\u003d1\\u0026y\\u003d2\",1]"]]'
    assert parse_google_news_batch_response(raw) == "https://example.com/a?x=1&y=2"
