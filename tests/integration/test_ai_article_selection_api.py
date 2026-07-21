import json
import threading
import time

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


class BlockingSelectionOllama:
    context_length = 65_536

    def __init__(self):
        self.started = threading.Event()

    def generate(self, *, model, prompt, format_schema=None, cancel_token=None):  # noqa: ARG002
        self.started.set()
        while True:
            cancel_token.raise_if_cancelled()
            time.sleep(0.005)

    def unload_model(self, model):  # noqa: ARG002
        return None


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
            "description": f"전기화재 예방과 전기안전 정책 관련 후보 내용 {index}",
            "category": "safety",
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
    data = applied.json()["data"]
    assert set(data["appliedArticleIds"]) == set(article_ids)
    assert "topIssueIssueIds" not in data
    assert "topIssueArticleIds" not in data
    assert "activatedTopIssueCount" not in data
    assert "topIssueCount" not in data
    after = client.get(f"/api/articles?report_date={report_date}").json()["data"]["articles"]
    assert all(item["included"] for item in after)
    assert not any(item["topIssue"] for item in after)


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


def test_apply_preserves_existing_selection_and_editor_state_and_top_issue():
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
    assert articles[article_ids[1]]["topIssue"] is False


def test_apply_preserves_existing_issue_top_tag_without_filling_empty_slots():
    report_date = "2025-04-07"
    article_ids, revision = setup_candidates(report_date, 4)
    grouped = client.post(
        "/api/issues/manual-group",
        json={
            "reportDate": report_date,
            "articleIds": article_ids[:2],
            "expectedRevision": revision,
        },
    )
    assert grouped.status_code == 200
    issue_id = grouped.json()["data"]["issue"]["id"]
    revision = grouped.json()["data"]["revision"]
    tagged = client.patch(
        f"/api/briefings/{report_date}/issues/{issue_id}",
        json={"expectedRevision": revision, "selected": True, "note": "기존 Top 이슈 메모"},
    )
    assert tagged.status_code == 200
    revision = tagged.json()["data"]["revision"]
    app.state.ollama_client = FakeSelectionOllama(recommendations(3))

    proposed = client.post(
        f"/api/briefings/{report_date}/selection-recommendations",
        json={"expectedRevision": revision, "model": "gemma-test"},
    )
    assert proposed.status_code == 200
    run = proposed.json()["data"]["run"]
    applied = client.post(
        f"/api/briefings/{report_date}/selection-recommendations/apply",
        json={"expectedRevision": revision, "runId": run["id"]},
    )

    assert applied.status_code == 200
    data = applied.json()["data"]
    assert "topIssueIssueIds" not in data
    assert "topIssueArticleIds" not in data
    assert "activatedTopIssueCount" not in data
    assert "topIssueCount" not in data
    issues = client.get(
        "/api/issues", params={"report_date": report_date}
    ).json()["data"]["issues"]
    issue = next(item for item in issues if item["id"] == issue_id)
    assert issue["selected"] is True
    assert issue["note"] == "기존 Top 이슈 메모"
    articles = client.get(
        f"/api/articles?report_date={report_date}"
    ).json()["data"]["articles"]
    assert not any(item["topIssue"] for item in articles)


def test_apply_does_not_activate_top_tag_on_recommended_article_cluster():
    report_date = "2025-04-08"
    article_ids, revision = setup_candidates(report_date, 4)
    grouped = client.post(
        "/api/issues/manual-group",
        json={
            "reportDate": report_date,
            "articleIds": article_ids[:2],
            "expectedRevision": revision,
        },
    )
    assert grouped.status_code == 200
    issue_id = grouped.json()["data"]["issue"]["id"]
    revision = grouped.json()["data"]["revision"]
    app.state.ollama_client = FakeSelectionOllama(recommendations(3))

    proposed = client.post(
        f"/api/briefings/{report_date}/selection-recommendations",
        json={"expectedRevision": revision, "model": "gemma-test"},
    )
    assert proposed.status_code == 200
    applied = client.post(
        f"/api/briefings/{report_date}/selection-recommendations/apply",
        json={"expectedRevision": revision, "runId": proposed.json()["data"]["run"]["id"]},
    )

    assert applied.status_code == 200
    data = applied.json()["data"]
    assert "topIssueIssueIds" not in data
    assert "topIssueArticleIds" not in data
    assert "activatedTopIssueCount" not in data
    assert "topIssueCount" not in data
    issues = client.get(
        "/api/issues", params={"report_date": report_date}
    ).json()["data"]["issues"]
    assert next(item for item in issues if item["id"] == issue_id)["selected"] is False
    articles = client.get(
        f"/api/articles?report_date={report_date}"
    ).json()["data"]["articles"]
    assert not any(item["topIssue"] for item in articles if item["id"] in article_ids[:2])


def test_recommendation_selects_twelve_without_changing_top_issues():
    report_date = "2025-04-04"
    article_ids, revision = setup_candidates(report_date, 14)
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
    assert len(applied_ids) == 12
    assert "topIssueArticleIds" not in applied.json()["data"]
    assert "topIssueIssueIds" not in applied.json()["data"]
    assert "activatedTopIssueCount" not in applied.json()["data"]
    assert "topIssueCount" not in applied.json()["data"]
    articles = client.get(
        f"/api/articles?report_date={report_date}"
    ).json()["data"]["articles"]
    assert sum(item["included"] for item in articles) == 12
    assert not any(item["topIssue"] for item in articles)

    manually_added_id = next(article_id for article_id in article_ids if article_id not in applied_ids)
    manually_added = client.patch(
        f"/api/briefings/{report_date}/articles/{manually_added_id}",
        json={"expectedRevision": applied.json()["data"]["revision"], "selected": True},
    )
    assert manually_added.status_code == 200
    articles = client.get(
        f"/api/articles?report_date={report_date}"
    ).json()["data"]["articles"]
    assert sum(item["included"] for item in articles) == 13


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


def test_cancelled_recommendation_releases_lock_before_model_retry():
    report_date = "2025-04-09"
    _, revision = setup_candidates(report_date, 1)
    blocking = BlockingSelectionOllama()
    app.state.ollama_client = blocking
    responses = []

    thread = threading.Thread(
        target=lambda: responses.append(
            client.post(
                f"/api/briefings/{report_date}/selection-recommendations",
                json={"expectedRevision": revision, "model": "gemma4:31b"},
            )
        )
    )
    thread.start()
    assert blocking.started.wait(timeout=2)

    cancelled = client.post(f"/api/briefings/{report_date}/analysis/cancel")
    thread.join(timeout=2)

    assert cancelled.status_code == 200
    assert cancelled.json()["data"]["cleanupComplete"] is True
    assert not thread.is_alive()
    assert responses[0].json()["error"]["code"] == "AI_CANCELLED"

    app.state.ollama_client = FakeSelectionOllama(recommendations(1))
    retried = client.post(
        f"/api/briefings/{report_date}/selection-recommendations",
        json={"expectedRevision": revision, "model": "gemma4:26b"},
    )

    assert retried.status_code == 200, retried.json()
    assert retried.json()["data"]["run"]["model"] == "gemma4:26b"
