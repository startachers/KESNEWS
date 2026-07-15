import json

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.services.ai.ollama_client import OllamaError

client = TestClient(app)


def valid_analysis() -> dict:
    return {
        "managementMessage": {"text": "경영 메시지", "articleIds": ["A01"]},
        "situationSummary": {"text": "상황 요약", "articleIds": ["A01"]},
        "keyIssues": [{"title": "이슈", "urgency": "required", "summary": "요약", "managementImpact": "영향", "articleIds": ["A01"]}],
        "decisionPoints": [{"text": "판단", "articleIds": ["A01"]}],
        "actionItems": [{"priority": "review", "action": "확인", "articleIds": ["A01"]}],
        "riskOutlook": {"text": "전망", "articleIds": ["A01"], "isInference": True},
        "limitations": [{"text": "본문 미확보", "articleIds": []}],
        "confidence": "medium",
    }


class FakeOllama:
    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts = []

    def generate(self, *, model, prompt):
        self.prompts.append((model, prompt))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return json.dumps(response, ensure_ascii=False) if isinstance(response, dict) else response


def setup_selected_article(report_date: str):
    briefing = client.put(
        f"/api/briefings/{report_date}", json={"expectedRevision": 0, "patch": {}}
    ).json()["data"]
    created = client.post(
        "/api/articles",
        json={
            "reportDate": report_date,
            "title": f"AI 분석 기사 {report_date}",
            "source": "테스트일보",
            "url": f"https://example.com/ai/{report_date}",
            "description": "한국전기안전공사 관련 확인된 기사 설명",
            "category": "direct",
        },
    ).json()["data"]
    return briefing, created["id"]


def run_analysis(report_date: str, fake: FakeOllama, model: str = "gemma-test"):
    app.state.ollama_client = fake
    revision = client.get(f"/api/briefings/{report_date}").json()["data"]["revision"]
    return client.post(
        f"/api/briefings/{report_date}/analyze",
        json={"expectedRevision": revision, "model": model},
    )


def test_valid_result_persists_fixed_evidence_and_structured_response():
    report_date = "2025-03-01"
    _, article_id = setup_selected_article(report_date)
    response = run_analysis(report_date, FakeOllama([valid_analysis()]))
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["run"]["evidence"] == {"A01": article_id}
    assert data["run"]["request"]["contextLength"] == 65_536
    assert data["run"]["response"]["analysis"]["decisionPoints"][0]["articleIds"] == ["A01"]
    assert data["summaryMode"] == "ai"
    loaded = client.get(f"/api/briefings/{report_date}").json()["data"]
    assert loaded["aiState"]["lastSuccessfulRun"]["response"]["analysis"]["confidence"] == "medium"


def test_unknown_a99_is_corrected_once_then_applied():
    report_date = "2025-03-02"
    setup_selected_article(report_date)
    invalid = valid_analysis()
    invalid["decisionPoints"][0]["articleIds"] = ["A99"]
    fake = FakeOllama([invalid, valid_analysis()])
    response = run_analysis(report_date, fake)
    assert response.status_code == 200
    assert len(fake.prompts) == 2
    assert "형식 교정 요청" in fake.prompts[1][1]
    assert response.json()["data"]["run"]["response"]["attempts"] == 2


def test_unknown_a99_after_correction_rejects_whole_result():
    report_date = "2025-03-07"
    setup_selected_article(report_date)
    invalid = valid_analysis()
    invalid["managementMessage"]["articleIds"] = ["A99"]
    fake = FakeOllama([invalid, invalid])
    response = run_analysis(report_date, fake)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "AI_EVIDENCE_INVALID"
    loaded = client.get(f"/api/briefings/{report_date}").json()["data"]
    assert loaded["situationSummary"] in (None, "")
    assert loaded["aiState"]["lastSuccessfulRun"] is None


def test_schema_failure_after_one_retry_rejects_whole_result():
    report_date = "2025-03-03"
    setup_selected_article(report_date)
    fake = FakeOllama([{"wrong": True}, {"stillWrong": True}])
    response = run_analysis(report_date, fake)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "AI_SCHEMA_INVALID"
    assert len(fake.prompts) == 2
    loaded = client.get(f"/api/briefings/{report_date}").json()["data"]
    assert loaded["aiState"]["lastSuccessfulRun"] is None
    assert "AI_SCHEMA_INVALID" in loaded["aiState"]["currentError"]


def test_selection_or_note_change_marks_success_stale_without_deleting_it():
    report_date = "2025-03-04"
    _, article_id = setup_selected_article(report_date)
    success = run_analysis(report_date, FakeOllama([valid_analysis()]))
    revision = success.json()["data"]["briefingRevision"]
    patched = client.patch(
        f"/api/briefings/{report_date}/articles/{article_id}",
        json={"expectedRevision": revision, "note": "변경된 담당자 메모"},
    )
    assert patched.status_code == 200
    loaded = client.get(f"/api/briefings/{report_date}").json()["data"]
    assert loaded["aiState"]["lastSuccessfulRun"]["stale"] is True
    assert loaded["aiState"]["lastSuccessfulRun"]["response"]["analysis"]


def test_ai_edited_summary_survives_reanalysis():
    report_date = "2025-03-05"
    setup_selected_article(report_date)
    first = run_analysis(report_date, FakeOllama([valid_analysis()])).json()["data"]
    edited_text = "담당자가 직접 수정한 요약"
    edited = client.put(
        f"/api/briefings/{report_date}",
        json={
            "expectedRevision": first["briefingRevision"],
            "patch": {"situationSummary": edited_text, "summaryMode": "ai-edited"},
        },
    ).json()["data"]
    second = run_analysis(report_date, FakeOllama([valid_analysis()]))
    assert second.status_code == 200
    assert second.json()["data"]["appliedToSummary"] is False
    loaded = client.get(f"/api/briefings/{report_date}").json()["data"]
    assert loaded["revision"] == edited["revision"] + 1
    assert loaded["situationSummary"] == edited_text
    assert loaded["summaryMode"] == "ai-edited"


def test_ollama_offline_returns_last_success_and_current_error_together():
    report_date = "2025-03-06"
    setup_selected_article(report_date)
    first = run_analysis(report_date, FakeOllama([valid_analysis()]))
    assert first.status_code == 200
    failed = run_analysis(report_date, FakeOllama([OllamaError("offline")]))
    assert failed.status_code == 503
    details = failed.json()["error"]["details"]
    assert details["lastSuccessfulRun"]["response"]["analysis"]
    assert "AI_UNAVAILABLE" in details["currentError"]
    loaded = client.get(f"/api/briefings/{report_date}").json()["data"]
    assert loaded["aiState"]["lastSuccessfulRun"]
    assert "AI_UNAVAILABLE" in loaded["aiState"]["currentError"]
