import pytest

from backend.app.services.extraction.article_body import BodyFetchResult


@pytest.fixture(autouse=True)
def disable_article_body_network(monkeypatch):
    """통합 테스트의 AI 실행이 실제 언론사나 example.com에 접속하지 않게 한다."""
    monkeypatch.setattr(
        "backend.app.api.analysis.article_body.fetch_article_body",
        lambda url: BodyFetchResult("", "missing", "테스트 네트워크 비활성화"),
    )
