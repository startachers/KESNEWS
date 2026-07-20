import json
import os
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.repositories import article_repository as article_repo
from backend.app.repositories.database import get_connection
from backend.app.services.analysis_markdown import service as markdown_service
from backend.app.services.analysis_markdown.config import DEFAULT_PATH
from backend.app.services.analysis_markdown.signature import input_signature as real_input_signature
from backend.app.services.extraction.article_body import BodyFetchResult

client = TestClient(app)


def _add_selected(
    report_date: str,
    suffix: str,
    description: str,
    priority: str,
    *,
    title: str | None = None,
) -> str:
    response = client.post(
        "/api/articles",
        json={
            "reportDate": report_date,
            "title": title or f"전기안전 현장 점검 결과 {suffix}",
            "source": "연합뉴스",
            "url": f"https://www.yna.co.kr/view/{report_date.replace('-', '')}{suffix}",
            "pubDate": f"{report_date}T01:00:00Z",
            "description": description,
            "category": "electrical_accident",
        },
    )
    article_id = response.json()["data"]["id"]
    connection = get_connection()
    try:
        with connection:
            connection.execute(
                "UPDATE article_assessments SET final_priority = ? WHERE article_id = ?",
                (priority, article_id),
            )
    finally:
        connection.close()
    briefing = client.get(f"/api/briefings/{report_date}").json()["data"]
    patched = client.patch(
        f"/api/briefings/{report_date}/articles/{article_id}",
        json={"expectedRevision": briefing["revision"], "selected": True, "note": f"메모-{suffix}"},
    )
    assert patched.status_code == 200
    return article_id


def test_required_article_failure_blocks_generation(monkeypatch):
    report_date = "2097-07-01"
    client.put(f"/api/briefings/{report_date}", json={"expectedRevision": 0, "patch": {}})
    article_id = _add_selected(report_date, "required", "", "required")
    monkeypatch.setattr(
        "backend.app.services.analysis_markdown.service.fetch_article_body_with_retries",
        lambda url, **kwargs: BodyFetchResult("", "failed", "access_blocked"),
    )
    monkeypatch.setattr(
        "backend.app.services.analysis_markdown.service.search_trusted_candidates", lambda article: []
    )
    response = client.post(f"/api/briefings/{report_date}/analysis-markdown")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "REQUIRED_ARTICLE_EVIDENCE_MISSING"
    assert response.json()["error"]["details"]["failedArticles"][0]["articleId"] == article_id


def test_review_failure_is_excluded_and_valid_rss_is_included_without_ollama(monkeypatch):
    report_date = "2097-07-02"
    client.put(f"/api/briefings/{report_date}", json={"expectedRevision": 0, "patch": {"preparedBy": "홍보실"}})
    failed_id = _add_selected(report_date, "failed", "", "review")
    factual = "7월 2일 공사는 전기설비 현장 20곳의 안전점검을 완료하고 관계기관과 후속 조치 일정 및 재발 방지 계획을 협의했다고 밝혔다. " * 2
    valid_id = _add_selected(report_date, "valid", factual, "reference")
    calls = {"ollama": 0}

    class NoOllama:
        def generate(self, **kwargs):
            calls["ollama"] += 1
            raise AssertionError("Ollama must not be called")

    app.state.ollama_client = NoOllama()
    monkeypatch.setattr(
        "backend.app.services.analysis_markdown.service.fetch_article_body_with_retries",
        lambda url, **kwargs: BodyFetchResult("", "failed", "selector_failed"),
    )
    monkeypatch.setattr(
        "backend.app.services.analysis_markdown.service.search_trusted_candidates", lambda article: []
    )
    response = client.post(f"/api/briefings/{report_date}/analysis-markdown")
    assert response.status_code == 200
    result = response.json()["data"]
    assert Path(result["mdPath"]).is_relative_to(Path(os.environ["KESCO_REPORTS_DIR"]))
    assert result["eligibleCount"] == 1
    assert result["excludedCount"] == 1
    assert result["articles"][0 if result["articles"][0]["articleId"] == failed_id else 1]["analysisEligible"] is False
    assert any(item["articleId"] == valid_id for item in result["articles"])
    assert calls["ollama"] == 0


def test_generation_is_reproducible_and_note_changes_signature(monkeypatch):
    report_date = "2097-07-03"
    client.put(f"/api/briefings/{report_date}", json={"expectedRevision": 0, "patch": {}})
    factual = "7월 3일 공사는 전기설비 30곳을 점검했고 관계기관이 피해 수치와 후속 일정, 안전 대책을 공식 발표했다고 밝혔다. " * 12
    article_id = _add_selected(report_date, "stable", factual, "required")
    monkeypatch.setattr(
        "backend.app.services.analysis_markdown.service.fetch_article_body_with_retries",
        lambda url, **kwargs: BodyFetchResult("", "failed", "network_error"),
    )
    monkeypatch.setattr(
        "backend.app.services.analysis_markdown.service.search_trusted_candidates", lambda article: []
    )
    first = client.post(f"/api/briefings/{report_date}/analysis-markdown").json()["data"]
    second = client.post(f"/api/briefings/{report_date}/analysis-markdown").json()["data"]
    assert first["inputSignature"] == second["inputSignature"]
    assert first["fileHash"] == second["fileHash"]
    briefing = client.get(f"/api/briefings/{report_date}").json()["data"]
    client.patch(
        f"/api/briefings/{report_date}/articles/{article_id}",
        json={"expectedRevision": briefing["revision"], "note": "변경된 담당자 메모"},
    )
    changed = client.post(f"/api/briefings/{report_date}/analysis-markdown").json()["data"]
    assert changed["inputSignature"] != first["inputSignature"]
    assert changed["fileHash"] != first["fileHash"]


def test_searched_replacement_is_persisted_as_separate_article(monkeypatch):
    report_date = "2097-07-04"
    client.put(f"/api/briefings/{report_date}", json={"expectedRevision": 0, "patch": {}})
    original_id = _add_selected(report_date, "replacement", "", "required")
    replacement_body = "7월 4일 관계기관은 전기안전 현장 점검 결과와 피해 수치, 조사 일정, 재발 방지 대책을 공식 발표했다고 밝혔다. " * 12
    monkeypatch.setattr(
        "backend.app.services.analysis_markdown.service.fetch_article_body_with_retries",
        lambda url, **kwargs: (
            BodyFetchResult(replacement_body, "success_full", resolved_url=url)
            if "kbs.co.kr" in url
            else BodyFetchResult("", "failed", "access_blocked")
        ),
    )
    monkeypatch.setattr(
        "backend.app.services.analysis_markdown.service.search_trusted_candidates",
        lambda article: [{
            "id": "search-temp-id",
            "title": "전기안전 현장 점검 결과 replacement 후속",
            "source": "KBS",
            "url": "https://news.kbs.co.kr/news/view.do?ncd=1",
            "pubDate": "2097-07-04T02:00:00Z",
            "description": "",
            "provider": "Google 뉴스 RSS",
            "publisherId": "kbs",
            "publisherAllowed": True,
            "bodyText": "",
            "priority": "required",
        }],
    )
    response = client.post(f"/api/briefings/{report_date}/analysis-markdown")
    assert response.status_code == 200
    result = response.json()["data"]
    assert result["replacementCount"] == 1
    replacement_id = result["articles"][0]["replacementArticleId"]
    assert replacement_id and replacement_id != original_id
    connection = get_connection()
    try:
        original = connection.execute("SELECT body_text FROM articles WHERE id = ?", (original_id,)).fetchone()
        link = connection.execute(
            "SELECT replaces_article_id FROM article_extractions WHERE article_id = ? ORDER BY created_at DESC LIMIT 1",
            (replacement_id,),
        ).fetchone()
        assert not original["body_text"]
        assert link["replaces_article_id"] == original_id
    finally:
        connection.close()


def test_document_budget_signature_uses_final_included_articles(tmp_path, monkeypatch):
    report_date = "2097-07-05"
    client.put(f"/api/briefings/{report_date}", json={"expectedRevision": 0, "patch": {}})
    factual = (
        "관계기관은 전기설비 안전점검 결과와 피해 수치, 후속 조사 일정 및 재발 방지 계획을 공식 발표했다. "
        * 18
    )
    _add_selected(
        report_date,
        "budget-a",
        factual,
        "reference",
        title="동해안 변전소 침수 대비 안전진단 결과 발표",
    )
    _add_selected(
        report_date,
        "budget-b",
        factual,
        "reference",
        title="제주 태양광 설비 사용전검사 제도 개선 계획",
    )
    config = json.loads(DEFAULT_PATH.read_text(encoding="utf-8"))
    config["article_character_limits"]["reference"] = 900
    config["document_budget"] = {"warning_characters": 2500, "max_characters": 3500}
    config_path = tmp_path / "analysis-markdown.json"
    config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    captured: list[dict] = []

    def capture(payload):
        captured.append(payload)
        return real_input_signature(payload)

    monkeypatch.setattr(markdown_service, "input_signature", capture)
    output = markdown_service.generate(
        get_connection,
        report_date,
        allow_network=False,
        config_path=config_path,
    )

    assert output.result["eligibleCount"] == 1
    assert any(item["reason"] == "document_budget" for item in output.result["excludedArticles"])
    assert [item["analysisEligible"] for item in captured[-1]["articles"]].count(False) == 1
    assert output.result["inputSignature"] == real_input_signature(captured[-1])
    assert output.result["inputSignature"] in output.content


def test_searched_replacement_does_not_fuzzy_merge_a_different_url():
    connection = get_connection()
    try:
        with connection:
            existing_id = article_repo.create_article(
                connection,
                url="https://news.example.com/events/one",
                title="전기안전 현장 점검 결과와 후속 대책 발표",
                source="테스트일보",
                published_at="2097-07-06T01:00:00Z",
                description="",
                category_hint="electrical_accident",
                manual=False,
            )
            replacement = markdown_service._persist_searched_article(
                connection,
                {
                    "id": "temporary-search-id",
                    "resolvedUrl": "https://news.example.com/events/two",
                    "url": "https://news.example.com/events/two",
                    "title": "전기안전 현장 점검 결과와 후속 대책 발표",
                    "source": "테스트일보",
                    "pubDate": "2097-07-06T01:00:00Z",
                    "description": "별개의 사건 기사",
                    "category": "electrical_accident",
                },
                original_article_id="unrelated-original",
            )
        assert replacement["id"] != existing_id
    finally:
        connection.close()
