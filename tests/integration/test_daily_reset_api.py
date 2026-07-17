from fastapi.testclient import TestClient

from backend.app.api import briefings as briefings_api
from backend.app.core.clock import now_iso
from backend.app.main import app
from backend.app.repositories.database import BACKUPS_DIR, get_connection

client = TestClient(app)


def create_briefing(report_date: str) -> dict:
    response = client.put(
        f"/api/briefings/{report_date}", json={"expectedRevision": 0, "patch": {}}
    )
    assert response.status_code == 200
    return response.json()["data"]


def create_article(report_date: str, suffix: str) -> str:
    response = client.post("/api/articles", json={
        "reportDate": report_date,
        "title": f"한국전기안전공사 오늘 작업 기사 {suffix}",
        "source": "초기화테스트일보",
        "url": f"https://reset.example.com/{report_date}/{suffix}",
        "description": "한국전기안전공사 전기안전 점검 관련 기사",
        "category": "kesco_direct",
    })
    assert response.status_code == 200
    return response.json()["data"]["id"]


def seed_run_records(report_date: str, briefing_id: str, article_id: str) -> None:
    now = now_iso()
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO collection_runs (
                id, report_date, started_at, finished_at, status, lookback_hours,
                raw_count, accepted_count, unique_count, stale_reused_count,
                warning_count, error_count
            ) VALUES ('reset-collection', ?, ?, ?, 'success', 24, 1, 1, 1, 0, 0, 0)
            """,
            (report_date, now, now),
        )
        connection.execute(
            """
            INSERT INTO collection_run_providers (
                id, collection_run_id, provider, status, started_at, finished_at,
                raw_count, accepted_count, duplicate_count, stale_reused_count
            ) VALUES ('reset-provider', 'reset-collection', 'reset-test', 'success', ?, ?, 1, 1, 0, 0)
            """,
            (now, now),
        )
        connection.execute(
            """
            INSERT INTO article_observations (
                id, article_id, collection_run_provider_id, provider, raw_title, observed_at
            ) VALUES ('reset-observation', ?, 'reset-provider', 'reset-test', '초기화 기사', ?)
            """,
            (article_id, now),
        )
        connection.execute(
            """
            INSERT INTO ai_runs (
                id, briefing_id, model, prompt_version, input_signature, status,
                request_json, response_json, evidence_json, started_at, finished_at
            ) VALUES ('reset-ai-run', ?, 'gemma-test', 'test-v1', 'sig', 'success',
                      '{}', '{}', '{}', ?, ?)
            """,
            (briefing_id, now, now),
        )
        connection.execute(
            """
            INSERT INTO ai_selection_runs (
                id, briefing_id, model, prompt_version, input_signature, status,
                request_json, response_json, evidence_json, started_at, finished_at
            ) VALUES ('reset-selection-run', ?, 'gemma-test', 'test-v1', 'sig', 'success',
                      '{}', '{"recommendations": []}', '{}', ?, ?)
            """,
            (briefing_id, now, now),
        )
        connection.execute(
            """
            INSERT INTO briefing_report_drafts (
                briefing_id, source_type, source_label, content_json, evidence_json,
                input_signature, based_on_ai_run_id, created_at, updated_at
            ) VALUES (?, 'manual', '초기화 테스트', '{}', '{}', 'sig', 'reset-ai-run', ?, ?)
            """,
            (briefing_id, now, now),
        )


def test_reset_today_deletes_work_but_preserves_article_origin_and_other_date(monkeypatch):
    report_date = "2099-01-03"
    other_date = "2099-01-02"
    monkeypatch.setattr(briefings_api, "today_seoul", lambda: report_date)
    briefing = create_briefing(report_date)
    first = create_article(report_date, "first")
    second = create_article(report_date, "second")
    revision = client.get(f"/api/briefings/{report_date}").json()["data"]["revision"]
    grouped = client.post("/api/issues/manual-group", json={
        "reportDate": report_date,
        "articleIds": [first, second],
        "expectedRevision": revision,
    }).json()["data"]
    issue_id = grouped["issue"]["id"]
    revision = grouped["revision"]
    tagged_issue = client.patch(
        f"/api/briefings/{report_date}/issues/{issue_id}",
        json={"expectedRevision": revision, "selected": True, "note": "삭제할 이슈 메모"},
    ).json()["data"]
    revision = tagged_issue["revision"]
    edited = client.patch(
        f"/api/briefings/{report_date}/articles/{first}",
        json={
            "expectedRevision": revision,
            "selected": True,
            "starred": True,
            "topIssue": True,
            "note": "삭제할 기사 메모",
        },
    ).json()["data"]
    revision = edited["revision"]
    updated = client.put(
        f"/api/briefings/{report_date}",
        json={
            "expectedRevision": revision,
            "patch": {
                "preparedBy": "삭제할 담당자",
                "situationSummary": "삭제할 요약",
                "actionNote": "삭제할 지시사항",
                "summaryMode": "manual",
            },
        },
    ).json()["data"]
    revision = updated["revision"]
    seed_run_records(report_date, briefing["id"], first)

    other = create_briefing(other_date)
    other_article = create_article(other_date, "other-date")
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO issue_review_assessments (
                briefing_id, issue_id, auto_score, auto_rank, auto_stars,
                reasons_json, scoring_version, calculated_at, updated_at
            ) VALUES (?, ?, 80, 1, 4, '{}', 'review-v1', ?, ?)
            """,
            (other["id"], issue_id, now_iso(), now_iso()),
        )
    before_backups = set(BACKUPS_DIR.glob("*.db"))
    response = client.post(
        f"/api/briefings/{report_date}/reset",
        json={"expectedRevision": revision, "confirmation": "RESET_TODAY"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["revision"] == revision + 1
    assert data["preparedBy"] is None
    assert data["situationSummary"] is None
    assert data["actionNote"] is None
    assert data["deleted"] == {
        "articles": 2,
        "issues": 1,
        "collectionRuns": 1,
        "aiRuns": 1,
        "selectionRuns": 1,
    }
    assert data["backupFile"]
    assert set(BACKUPS_DIR.glob("*.db")) - before_backups
    assert client.get(
        "/api/articles", params={"report_date": report_date}
    ).json()["data"]["articles"] == []
    assert client.get(
        "/api/issues", params={"report_date": report_date}
    ).json()["data"]["issues"] == []
    with get_connection() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM articles WHERE id IN (?, ?)", (first, second)
        ).fetchone()[0] == 2
        assert connection.execute(
            "SELECT COUNT(*) FROM collection_runs WHERE report_date = ?", (report_date,)
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM ai_runs WHERE briefing_id = ?", (briefing["id"],)
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM briefing_report_drafts WHERE briefing_id = ?",
            (briefing["id"],),
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM issues WHERE id = ?", (issue_id,)
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM issue_review_assessments "
            "WHERE briefing_id = ? AND issue_id = ?",
            (other["id"], issue_id),
        ).fetchone()[0] == 1
        assert connection.execute(
            """
            SELECT COUNT(*) FROM cluster_runs
            WHERE report_date = ? AND status = 'reset'
            """,
            (report_date,),
        ).fetchone()[0] >= 1
    assert client.get(f"/api/briefings/{other_date}").json()["data"]["id"] == other["id"]
    other_articles = client.get(
        "/api/articles", params={"report_date": other_date}
    ).json()["data"]["articles"]
    assert [item["id"] for item in other_articles] == [other_article]


def test_reset_rejects_historical_final_and_stale_work_without_deleting(monkeypatch):
    today = "2099-01-05"
    historical = "2099-01-04"
    monkeypatch.setattr(briefings_api, "today_seoul", lambda: today)
    historical_briefing = create_briefing(historical)
    historical_article = create_article(historical, "historical")
    historical_revision = client.get(
        f"/api/briefings/{historical}"
    ).json()["data"]["revision"]
    historical_response = client.post(
        f"/api/briefings/{historical}/reset",
        json={"expectedRevision": historical_revision, "confirmation": "RESET_TODAY"},
    )
    assert historical_response.status_code == 400
    assert historical_response.json()["error"]["code"] == "DAILY_RESET_TODAY_ONLY"

    today_briefing = create_briefing(today)
    today_article = create_article(today, "today")
    current_revision = client.get(f"/api/briefings/{today}").json()["data"]["revision"]
    stale_response = client.post(
        f"/api/briefings/{today}/reset",
        json={"expectedRevision": current_revision - 1, "confirmation": "RESET_TODAY"},
    )
    assert stale_response.status_code == 409
    assert stale_response.json()["error"]["code"] == "BRIEFING_REVISION_CONFLICT"
    with get_connection() as connection:
        connection.execute(
            "UPDATE briefings SET status = 'final' WHERE id = ?", (today_briefing["id"],)
        )
    final_response = client.post(
        f"/api/briefings/{today}/reset",
        json={"expectedRevision": current_revision, "confirmation": "RESET_TODAY"},
    )
    assert final_response.status_code == 409
    assert final_response.json()["error"]["code"] == "BRIEFING_FINALIZED"
    for report_date, article_id, briefing_id in (
        (historical, historical_article, historical_briefing["id"]),
        (today, today_article, today_briefing["id"]),
    ):
        articles = client.get(
            "/api/articles", params={"report_date": report_date}
        ).json()["data"]["articles"]
        assert [item["id"] for item in articles] == [article_id]
        assert client.get(f"/api/briefings/{report_date}").json()["data"]["id"] == briefing_id
