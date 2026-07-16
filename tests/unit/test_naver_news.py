import json
import os
from urllib.parse import parse_qs, urlsplit

from backend.app.core.env import load_env
from backend.app.services.collection import naver_news


def _raw_item(index: int, pub_date: str = "Wed, 15 Jan 2025 09:00:00 +0900") -> dict:
    return {
        "title": f"<b>전기안전</b> 기사 &amp; 소식 {index}",
        "originallink": f"https://www.yna.co.kr/view/{index}",
        "link": f"https://n.news.naver.com/article/001/{index}",
        "pubDate": pub_date,
        "description": "<b>설명</b> &lt;확인&gt;",
    }


def test_env_loader_parses_simple_values_and_preserves_existing(monkeypatch, tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        "# comment\nNAVER_CLIENT_ID=file-id\nNAVER_CLIENT_SECRET='file secret'\nINVALID LINE\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("NAVER_CLIENT_ID", "process-id")
    monkeypatch.delenv("NAVER_CLIENT_SECRET", raising=False)

    assert load_env(path) == 1
    assert os.environ["NAVER_CLIENT_ID"] == "process-id"
    assert os.environ["NAVER_CLIENT_SECRET"] == "file secret"


def test_normalize_naver_item_cleans_html_and_preserves_original_link():
    item = naver_news.normalize_naver_item(_raw_item(1))
    assert item["title"] == "전기안전 기사 & 소식 1"
    assert item["description"] == "설명 <확인>"
    assert item["pubDate"] == "2025-01-15T00:00:00Z"
    assert item["url"] == "https://www.yna.co.kr/view/1"
    assert item["originalLink"] == item["url"]
    assert item["naverUrl"].startswith("https://n.news.naver.com/")
    assert "sourceId" not in item


def test_pagination_stops_at_lookback_boundary(monkeypatch):
    starts = []

    def fake_get(url, headers, timeout):
        starts.append(int(parse_qs(urlsplit(url).query)["start"][0]))
        assert headers["X-Naver-Client-Id"] == "client-id"
        assert headers["X-Naver-Client-Secret"] == "client-secret"
        assert timeout == 15
        items = [_raw_item(i + starts[-1]) for i in range(100)]
        if starts[-1] == 101:
            items[-1] = _raw_item(999, "Sun, 12 Jan 2025 09:00:00 +0900")
        return 200, json.dumps({"items": items})

    monkeypatch.setattr(naver_news, "http_get", fake_get)
    items = naver_news.fetch_naver_news(
        "전기안전", "client-id", "client-secret", lambda value: value >= "2025-01-14"
    )
    assert starts == [1, 101]
    assert len(items) == 199


def test_pagination_never_exceeds_three_pages(monkeypatch):
    starts = []

    def fake_get(url, headers, timeout):  # noqa: ARG001
        starts.append(int(parse_qs(urlsplit(url).query)["start"][0]))
        return 200, json.dumps({"items": [_raw_item(i + starts[-1]) for i in range(100)]})

    monkeypatch.setattr(naver_news, "http_get", fake_get)
    items = naver_news.fetch_naver_news("전력망", "id", "secret", lambda value: True)
    assert starts == [1, 101, 201]
    assert len(items) == 300


def test_rate_limit_response_is_retried_without_exposing_credentials(monkeypatch):
    calls = []

    def fake_get(url, headers, timeout):  # noqa: ARG001
        calls.append(headers.copy())
        if len(calls) == 1:
            return 429, '{"errorMessage":"rate limited"}'
        return 200, json.dumps({"items": [_raw_item(1)]})

    monkeypatch.setattr(naver_news, "http_get", fake_get)
    monkeypatch.setattr(naver_news, "REQUEST_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(naver_news, "_defer_requests", lambda seconds: None)
    items = naver_news.fetch_naver_news("전기안전", "private-id", "private-secret", lambda v: True)

    assert len(calls) == 2
    assert len(items) == 1
