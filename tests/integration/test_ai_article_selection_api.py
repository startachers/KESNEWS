import json

from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)


class FakeSelectionOllama:
    context_length = 65_536

    def __init__(self, response):
        self.response = response
        self.prompts = []

    def generate(self, *, model, prompt, format_schema=None, cancel_token=None):  # noqa: ARG002
        self.prompts.append(prompt)
        return json.dumps(self.response, ensure_ascii=False)


def setup_candidates(report_date: str, count: int = 3):
    briefing = client.put(
        f"/api/briefings/{report_date}", json={"expectedRevision": 0, "patch": {}}
    ).json()["data"]
    article_ids = []
    revision = briefing["revision"]
    for index in range(count):
        created = client.post("/api/articles", json={
            "reportDate": report_date,
            "title": f"전기안전 경영 현안 후보 {index}",
            "source": f"테스트일보 {index}",
            "url": f"https://example.com/selection/{report_date}/{index}",
            "description": f"한국전기안전공사 관련 후보 내용 {index}",
            "category": "kesco_direct",
        }).json()["data"]
        article_ids.append(created["id"])
        revision = client.get(f"/api/briefings/{report_date}").json()["data"]["revision"]
        patched = client.patch(
            f"/api/briefings/{report_date}/articles/{created['id']}",
            json={"expectedRevision": revision, "selected": False},
        )
        revision = patched.json()["data"]["revision"]
    return article_ids, revision


def recommendations(count: int):
    return {
        "recommendations": [
            {
                "evidenceId": f"C{index:02d}",
                "rank": index,
                "articleFact": f"기사 사실 {index}",
                "kescoRelevance": f"공사 연관성 {index}",
                "selectionReason": f"선정 이유 {index}",
            }
            for index in range(1, count + 1)
        ],
        "limitations": [],
    }


def test_recommendation_does_not_mutate_until_explicit_apply():
    report_date = "2025-04-01"
    article_ids, revision = setup_candidates(report_date)
    app.state.ollama_client = FakeSelectionOllama(recommendations(3))

    proposed = client.post(
        f"/api/briefings/{report_date}/selection-recommendations",
        json={"expectedRevision": revision, "model": "gemma-test"},
    )
    assert proposed.status_code == 200
    run = proposed.json()["data"]["run"]
    assert run["status"] == "success"
    assert client.get(f"/api/briefings/{report_date}").json()["data"]["revision"] == revision
    before = client.get(f"/api/articles?report_date={report_date}").json()["data"]["articles"]
    assert not any(item["included"] for item in before)

    applied = client.post(
        f"/api/briefings/{report_date}/selection-recommendations/apply",
        json={"expectedRevision": revision, "runId": run["id"]},
    )
    assert applied.status_code == 200
    assert set(applied.json()["data"]["appliedArticleIds"]) == set(article_ids)
    assert set(applied.json()["data"]["topIssueArticleIds"]) == set(article_ids)
    after = client.get(f"/api/articles?report_date={report_date}").json()["data"]["articles"]
    assert all(item["included"] for item in after)
    assert all(item["topIssue"] for item in after)


def test_recommendation_rejects_fewer_than_available_candidates():
    report_date = "2025-04-05"
    article_ids, revision = setup_candidates(report_date, 3)
    app.state.ollama_client = FakeSelectionOllama(recommendations(1))

    proposed = client.post(
        f"/api/briefings/{report_date}/selection-recommendations",
        json={"expectedRevision": revision, "model": "gemma-test"},
    )

    assert proposed.status_code == 422
    assert proposed.json()["error"]["code"] == "AI_SELECTION_SCHEMA_INVALID"
    assert "정확히 3건" in proposed.json()["error"]["message"]
    assert client.get(f"/api/briefings/{report_date}").json()["data"]["revision"] == revision
    assert article_ids


def test_recommendation_rejects_zero_when_candidates_exist():
    report_date = "2025-04-06"
    _, revision = setup_candidates(report_date, 2)
    app.state.ollama_client = FakeSelectionOllama(recommendations(0))

    proposed = client.post(
        f"/api/briefings/{report_date}/selection-recommendations",
        json={"expectedRevision": revision, "model": "gemma-test"},
    )

    assert proposed.status_code == 422
    assert proposed.json()["error"]["code"] == "AI_SELECTION_SCHEMA_INVALID"
    assert "정확히 2건" in proposed.json()["error"]["message"]
    assert client.get(f"/api/briefings/{report_date}").json()["data"]["revision"] == revision


def test_apply_preserves_existing_selection_and_article_editor_state():
    report_date = "2025-04-02"
    article_ids, revision = setup_candidates(report_date, 2)
    first = client.patch(
        f"/api/briefings/{report_date}/articles/{article_ids[0]}",
        json={"expectedRevision": revision, "selected": True, "starred": True, "topIssue": True, "note": "수동 메모"},
    ).json()["data"]
    app.state.ollama_client = FakeSelectionOllama(recommendations(1))
    proposed = client.post(
        f"/api/briefings/{report_date}/selection-recommendations",
        json={"expectedRevision": first["revision"], "model": "gemma-test"},
    ).json()["data"]["run"]
    applied = client.post(
        f"/api/briefings/{report_date}/selection-recommendations/apply",
        json={"expectedRevision": first["revision"], "runId": proposed["id"]},
    )
    assert applied.status_code == 200
    articles = {item["id"]: item for item in client.get(f"/api/articles?report_date={report_date}").json()["data"]["articles"]}
    assert articles[article_ids[0]]["included"] is True
    assert articles[article_ids[0]]["starred"] is True
    assert articles[article_ids[0]]["topIssue"] is True
    assert articles[article_ids[0]]["note"] == "수동 메모"
    assert articles[article_ids[1]]["included"] is True


def test_recommendation_selects_twelve_and_fills_six_top_issue_cards():
    report_date = "2025-04-04"
    _, revision = setup_candidates(report_date, 14)
    app.state.ollama_client = FakeSelectionOllama(recommendations(12))

    proposed = client.post(
        f"/api/briefings/{report_date}/selection-recommendations",
        json={"expectedRevision": revision, "model": "gemma-test"},
    ).json()["data"]["run"]
    applied = client.post(
        f"/api/briefings/{report_date}/selection-recommendations/apply",
        json={"expectedRevision": revision, "runId": proposed["id"]},
    )

    assert applied.status_code == 200
    assert applied.json()["data"]["selectedCount"] == 12
    applied_ids = applied.json()["data"]["appliedArticleIds"]
    top_issue_ids = applied.json()["data"]["topIssueArticleIds"]
    assert len(applied_ids) == 12
    assert top_issue_ids == applied_ids[:6]
    articles = client.get(
        f"/api/articles?report_date={report_date}"
    ).json()["data"]["articles"]
    assert sum(item["included"] for item in articles) == 12
    assert sum(item["topIssue"] for item in articles) == 6


def test_unknown_or_duplicate_candidate_ids_are_rejected_after_retry():
    report_date = "2025-04-03"
    _, revision = setup_candidates(report_date, 2)
    invalid = {
        "recommendations": [
            {"evidenceId": "C99", "rank": 1, "articleFact": "잘못된 ID", "kescoRelevance": "없음", "selectionReason": "오류"},
            {"evidenceId": "C99", "rank": 2, "articleFact": "중복 ID", "kescoRelevance": "없음", "selectionReason": "오류"},
        ],
        "limitations": [],
    }
    fake = FakeSelectionOllama(invalid)
    app.state.ollama_client = fake
    response = client.post(
        f"/api/briefings/{report_date}/selection-recommendations",
        json={"expectedRevision": revision, "model": "gemma-test"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "AI_SELECTION_SCHEMA_INVALID"
    assert len(fake.prompts) == 2
