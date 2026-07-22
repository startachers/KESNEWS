import json

from fastapi.testclient import TestClient

from backend.app.main import app


client = TestClient(app)


def _create_briefing_with_article(report_date: str) -> tuple[str, int]:
    created = client.put(
        f"/api/briefings/{report_date}",
        json={"expectedRevision": 0, "patch": {"preparedBy": "홍보실"}},
    )
    article = client.post(
        "/api/articles",
        json={
            "reportDate": report_date,
            "title": "전기안전 취약시설 집중 점검",
            "source": "테스트일보",
            "url": "https://example.com/summary-test",
            "description": "취약시설 120곳을 대상으로 특별점검을 실시하고 개선이 필요한 설비를 확인했다.",
            "category": "direct",
        },
    )
    return article.json()["data"]["id"], created.json()["data"]["revision"]


def test_preview_article_summary_replaces_no_data_and_keeps_revision(monkeypatch):
    report_date = "2026-10-01"
    article_id, revision = _create_briefing_with_article(report_date)

    class FakeOllama:
        def generate(self, *, model, prompt, format_schema=None, cancel_token=None):
            assert model == "gemma-test"
            assert article_id in prompt
            assert format_schema["properties"]["items"]["type"] == "array"
            assert cancel_token is not None
            return json.dumps(
                {
                    "items": [
                        {
                            "articleId": article_id,
                            "summary": "취약시설 120곳을 특별점검해 개선이 필요한 전기설비를 확인했다.",
                        }
                    ]
                },
                ensure_ascii=False,
            )

        def unload_model(self, model):
            assert model == "gemma-test"

    monkeypatch.setattr(app.state, "ollama_client", FakeOllama(), raising=False)
    response = client.post(
        f"/api/briefings/{report_date}/article-summaries",
        json={"model": "gemma-test"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["sourceRevision"] == revision
    assert data["summaries"] == [
        {
            "articleId": article_id,
            "summary": "취약시설 120곳을 특별점검해 개선이 필요한 전기설비를 확인했다.",
        }
    ]
    unchanged = client.get(f"/api/briefings/{report_date}").json()["data"]
    assert unchanged["revision"] == revision


def test_preview_article_summary_rejects_missing_article_result(monkeypatch):
    report_date = "2026-10-02"
    _create_briefing_with_article(report_date)

    class InvalidOllama:
        def generate(self, **kwargs):
            return json.dumps({"items": []})

    monkeypatch.setattr(app.state, "ollama_client", InvalidOllama(), raising=False)
    response = client.post(
        f"/api/briefings/{report_date}/article-summaries",
        json={"model": "gemma-test"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "AI_SCHEMA_INVALID"


def test_preview_article_summary_rewrites_title_repetition(monkeypatch):
    report_date = "2026-10-03"
    article_id, _ = _create_briefing_with_article(report_date)

    class RevisingOllama:
        def __init__(self):
            self.calls = 0

        def generate(self, *, prompt, **kwargs):
            self.calls += 1
            if self.calls == 1:
                summary = "전기안전 취약시설을 집중 점검했습니다."
            else:
                assert "제목의 내용을 다시 반복해 부적합" in prompt
                summary = "점검 대상 120곳에서 개선이 필요한 전기설비를 확인했습니다."
            return json.dumps(
                {"items": [{"articleId": article_id, "summary": summary}]},
                ensure_ascii=False,
            )

    fake = RevisingOllama()
    monkeypatch.setattr(app.state, "ollama_client", fake, raising=False)
    response = client.post(
        f"/api/briefings/{report_date}/article-summaries",
        json={"model": "gemma-test"},
    )

    assert response.status_code == 200
    assert fake.calls == 2
    assert response.json()["data"]["summaries"][0]["summary"].startswith("점검 대상 120곳")
