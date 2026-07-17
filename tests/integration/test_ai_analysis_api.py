import json
import threading
import time

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.services.ai.ollama_client import OllamaError
from backend.app.services.extraction.article_body import BodyFetchResult

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


def valid_basis() -> dict:
    return {
        "items": [
            {
                "section": "core",
                "articleFact": "한국전기안전공사 관련 내용이 기사에서 확인됐다.",
                "attributedClaim": "",
                "kescoInterpretation": "공사의 현장 안전관리 관점에서 살펴볼 사안이다.",
                "managementRecommendation": "관련 현황과 안내 내용을 확인할 필요가 있다.",
                "articleIds": ["A01"],
                "certainty": "confirmed",
            }
        ],
        "limitations": [],
        "confidence": "medium",
    }


def successful_responses(result: dict | None = None) -> list[dict]:
    return [valid_basis(), result or valid_analysis()]


class FakeOllama:
    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts = []

    def generate(self, *, model, prompt, format_schema=None, cancel_token=None):  # noqa: ARG002
        self.prompts.append((model, prompt))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return json.dumps(response, ensure_ascii=False) if isinstance(response, dict) else response


def setup_selected_article(report_date: str, *, title: str | None = None):
    briefing = client.put(
        f"/api/briefings/{report_date}", json={"expectedRevision": 0, "patch": {}}
    ).json()["data"]
    created = client.post(
        "/api/articles",
        json={
            "reportDate": report_date,
            "title": title or f"AI 분석 기사 {report_date}",
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
    response = run_analysis(report_date, FakeOllama(successful_responses()))
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["run"]["evidence"] == {"A01": article_id}
    assert data["run"]["request"]["contextLength"] == 65_536
    assert data["run"]["response"]["analysis"]["decisionPoints"][0]["articleIds"] == ["A01"]
    assert data["run"]["response"]["analysisBasis"]["items"][0]["certainty"] == "confirmed"
    assert data["run"]["response"]["validationWarnings"] == []
    assert data["summaryMode"] == "ai"
    assert data["situationSummary"] == (
        "① 오늘의 핵심\n경영 메시지\n\n"
        "② 경영 시사점\n상황 요약\n\n"
        "③ 참고 동향\n별도 참고 동향 없음."
    )
    loaded = client.get(f"/api/briefings/{report_date}").json()["data"]
    assert loaded["aiState"]["lastSuccessfulRun"]["response"]["analysis"]["confidence"] == "medium"


def test_grounding_warning_filters_bad_item_and_persists_diagnostic():
    report_date = "2025-03-11"
    setup_selected_article(report_date)
    basis = valid_basis()
    unsupported = dict(basis["items"][0])
    unsupported["articleFact"] = "기사에 없는 피해액 300억원이 확인됐다."
    basis["items"] = [unsupported, basis["items"][0]]

    response = run_analysis(report_date, FakeOllama([basis, valid_analysis()]))

    assert response.status_code == 200
    stored = response.json()["data"]["run"]["response"]
    assert len(stored["analysisBasis"]["items"]) == 1
    assert stored["validationWarnings"][0]["code"] == "UNSUPPORTED_NUMBER"
    assert stored["validationWarnings"][0]["resolution"] == "filtered"


def test_grounding_rejects_result_when_no_basis_item_passes():
    report_date = "2025-03-12"
    setup_selected_article(report_date)
    basis = valid_basis()
    basis["items"][0]["kescoInterpretation"] = "공사는 송전망 구축을 담당한다."

    response = run_analysis(report_date, FakeOllama([basis]))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "AI_GROUNDING_INVALID"
    loaded = client.get(f"/api/briefings/{report_date}").json()["data"]
    assert loaded["aiState"]["lastSuccessfulRun"] is None


def test_selected_article_full_text_is_fetched_and_used(monkeypatch):
    report_date = "2025-03-09"
    _, article_id = setup_selected_article(
        report_date, title="전문 수집 성공 여부를 확인하는 고유한 전기안전 현장 기사"
    )
    full_text = "전문에만 포함된 현장 안전점검 세부 내용입니다. " * 20
    monkeypatch.setattr(
        "backend.app.api.analysis.article_body.fetch_article_body",
        lambda url: BodyFetchResult(full_text, "full_text"),
    )
    response = run_analysis(report_date, FakeOllama(successful_responses()))
    assert response.status_code == 200
    evidence_article = response.json()["data"]["run"]["request"]["articles"][0]
    assert evidence_article["content"] == full_text
    assert evidence_article["bodyStatus"] == "full_text"
    assert evidence_article["bodyError"] == ""


def test_body_fetch_failure_keeps_rss_summary_and_records_error(monkeypatch):
    report_date = "2025-03-10"
    setup_selected_article(
        report_date, title="언론사 차단 시 RSS 폴백을 확인하는 고유한 경영 현안 기사"
    )
    monkeypatch.setattr(
        "backend.app.api.analysis.article_body.fetch_article_body",
        lambda url: BodyFetchResult("", "missing", "언론사 응답 HTTP 403"),
    )
    response = run_analysis(report_date, FakeOllama(successful_responses()))
    assert response.status_code == 200
    evidence_article = response.json()["data"]["run"]["request"]["articles"][0]
    assert evidence_article["content"] == "한국전기안전공사 관련 확인된 기사 설명"
    assert evidence_article["bodyStatus"] == "summary_only"
    assert evidence_article["bodyError"] == "언론사 응답 HTTP 403"


def test_unknown_a99_is_corrected_once_then_applied():
    report_date = "2025-03-02"
    setup_selected_article(report_date)
    invalid = valid_analysis()
    invalid["decisionPoints"][0]["articleIds"] = ["A99"]
    fake = FakeOllama([valid_basis(), invalid, valid_analysis()])
    response = run_analysis(report_date, fake)
    assert response.status_code == 200
    assert len(fake.prompts) == 3
    assert "형식 교정 요청" in fake.prompts[2][1]
    assert response.json()["data"]["run"]["response"]["attempts"] == 2


def test_unknown_a99_after_correction_rejects_whole_result():
    report_date = "2025-03-07"
    setup_selected_article(report_date)
    invalid = valid_analysis()
    invalid["managementMessage"]["articleIds"] = ["A99"]
    fake = FakeOllama([valid_basis(), invalid, invalid])
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
    success = run_analysis(report_date, FakeOllama(successful_responses()))
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
    first = run_analysis(report_date, FakeOllama(successful_responses())).json()["data"]
    edited_text = "담당자가 직접 수정한 요약"
    edited = client.put(
        f"/api/briefings/{report_date}",
        json={
            "expectedRevision": first["briefingRevision"],
            "patch": {"situationSummary": edited_text, "summaryMode": "ai-edited"},
        },
    ).json()["data"]
    second = run_analysis(report_date, FakeOllama(successful_responses()))
    assert second.status_code == 200
    assert second.json()["data"]["appliedToSummary"] is False
    loaded = client.get(f"/api/briefings/{report_date}").json()["data"]
    assert loaded["revision"] == edited["revision"] + 1
    assert loaded["situationSummary"] == edited_text
    assert loaded["summaryMode"] == "ai-edited"


def test_ollama_offline_returns_last_success_and_current_error_together():
    report_date = "2025-03-06"
    setup_selected_article(report_date)
    first = run_analysis(report_date, FakeOllama(successful_responses()))
    assert first.status_code == 200
    failed = run_analysis(report_date, FakeOllama([OllamaError("offline")]))
    assert failed.status_code == 503
    details = failed.json()["error"]["details"]
    assert details["lastSuccessfulRun"]["response"]["analysis"]
    assert "AI_UNAVAILABLE" in details["currentError"]
    loaded = client.get(f"/api/briefings/{report_date}").json()["data"]
    assert loaded["aiState"]["lastSuccessfulRun"]
    assert "AI_UNAVAILABLE" in loaded["aiState"]["currentError"]


def test_running_analysis_rejects_duplicate_and_can_be_cancelled():
    report_date = "2025-03-08"
    setup_selected_article(report_date)

    class BlockingOllama:
        def __init__(self):
            self.started = threading.Event()

        def generate(self, *, model, prompt, format_schema=None, cancel_token=None):  # noqa: ARG002
            self.started.set()
            while not cancel_token.is_cancelled():
                time.sleep(0.01)
            cancel_token.raise_if_cancelled()
            raise AssertionError("cancel token must raise")

    fake = BlockingOllama()
    app.state.ollama_client = fake
    revision = client.get(f"/api/briefings/{report_date}").json()["data"]["revision"]
    result = {}

    def run_blocking_analysis():
        result["response"] = client.post(
            f"/api/briefings/{report_date}/analyze",
            json={"expectedRevision": revision, "model": "gemma4:31b"},
        )

    thread = threading.Thread(target=run_blocking_analysis)
    thread.start()
    assert fake.started.wait(timeout=2)

    duplicate = client.post(
        f"/api/briefings/{report_date}/analyze",
        json={"expectedRevision": revision, "model": "gemma4:31b"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "AI_ALREADY_RUNNING"

    cancelled = client.post(f"/api/briefings/{report_date}/analysis/cancel")
    assert cancelled.status_code == 200
    thread.join(timeout=3)
    assert not thread.is_alive()
    assert result["response"].status_code == 409
    assert result["response"].json()["error"]["code"] == "AI_CANCELLED"

    loaded = client.get(f"/api/briefings/{report_date}").json()["data"]
    assert loaded["aiState"]["latestRun"]["status"] == "failed"
    assert "AI_CANCELLED" in loaded["aiState"]["currentError"]
