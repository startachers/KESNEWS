from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.repositories.database import get_connection

client = TestClient(app)


def test_frontend_exposes_reclustering_proposal_and_apply_controls():
    page = client.get("/")
    assert page.status_code == 200
    assert 'id="reclusterBtn"' in page.text
    assert 'id="clusterOverlay"' in page.text
    assert 'id="clusterApplyBtn"' in page.text
    assert 'id="clusterThreshold"' in page.text
    assert 'id="clusterRecalculateBtn"' in page.text

    feature = client.get("/js/features/clustering.js")
    assert feature.status_code == 200
    assert "createClusterRun(state.date, thresholdValue())" in feature.text
    assert "thresholdDirty" in feature.text
    assert "applyClusterRun(activeRun.id)" in feature.text


def _create_briefing(report_date: str) -> None:
    response = client.put(f"/api/briefings/{report_date}", json={"expectedRevision": 0, "patch": {}})
    assert response.status_code == 200


def _create_article(report_date: str, suffix: str, title: str, source: str, pub_date: str) -> str:
    response = client.post(
        "/api/articles",
        json={
            "reportDate": report_date,
            "title": title,
            "source": source,
            "url": f"https://cluster.example.com/{suffix}",
            "pubDate": pub_date,
            "description": "전주 완산구 아파트 변압기 고장으로 주민들이 불편을 겪었다",
            "category": "safety",
        },
    )
    assert response.status_code == 200
    return response.json()["data"]["id"]


def test_cluster_proposal_apply_and_issue_list_keep_distinct_articles():
    report_date = "2026-08-01"
    _create_briefing(report_date)
    first = _create_article(
        report_date, "same-1", "전주 아파트 대규모 정전 발생 500세대 불편", "연합뉴스",
        "2026-08-01T05:00:00Z",
    )
    second = _create_article(
        report_date, "same-2", "전주 완산구 아파트 정전…500가구 전력 끊겨", "KBS",
        "2026-08-01T08:00:00Z",
    )
    unrelated = _create_article(
        report_date, "other", "한국전기안전공사 여름철 전기화재 예방 캠페인", "지역일보",
        "2026-08-01T09:00:00Z",
    )

    proposed = client.post(
        "/api/cluster-runs", json={"reportDate": report_date, "asOf": "2026-08-01T12:00:00Z"}
    )
    assert proposed.status_code == 200
    run = proposed.json()["data"]
    assert run["status"] == "proposed"
    assert len(run["proposal"]) == 2
    assert len(run["diff"]["createdIssues"]) == 2

    applied = client.post(f"/api/cluster-runs/{run['id']}/apply")
    assert applied.status_code == 200
    assert applied.json()["data"]["status"] == "applied"

    issues = client.get("/api/issues", params={"report_date": report_date}).json()["data"]["issues"]
    assert {frozenset(issue["articleIds"]) for issue in issues} == {
        frozenset({first, second}),
        frozenset({unrelated}),
    }
    articles = client.get("/api/articles", params={"report_date": report_date}).json()["data"]["articles"]
    assert {item["id"] for item in articles} == {first, second, unrelated}


def test_cluster_run_accepts_similarity_threshold_and_rejects_out_of_range():
    report_date = "2026-08-05"
    _create_briefing(report_date)
    _create_article(
        report_date, "threshold-1", "전주 아파트 대규모 정전 발생", "연합뉴스",
        "2026-08-05T05:00:00Z",
    )

    proposed = client.post(
        "/api/cluster-runs",
        json={
            "reportDate": report_date,
            "asOf": "2026-08-05T12:00:00Z",
            "similarityThreshold": 0.55,
        },
    )
    assert proposed.status_code == 200
    reasons = proposed.json()["data"]["proposal"][0]["autoReasons"]["clustering"]
    assert reasons == {"pairThreshold": 0.55, "minimumCrossScore": 0.40}

    invalid = client.post(
        "/api/cluster-runs",
        json={"reportDate": report_date, "similarityThreshold": 0.20},
    )
    assert invalid.status_code == 422


def test_recluster_preserves_editor_fields_and_membership_remove_override():
    report_date = "2026-08-02"
    _create_briefing(report_date)
    first = _create_article(
        report_date, "preserve-1", "전주 아파트 대규모 정전 발생 500세대 불편", "연합뉴스",
        "2026-08-02T05:00:00Z",
    )
    second = _create_article(
        report_date, "preserve-2", "전주 완산구 아파트 정전…500가구 전력 끊겨", "KBS",
        "2026-08-02T08:00:00Z",
    )
    run_id = client.post(
        "/api/cluster-runs", json={"reportDate": report_date, "asOf": "2026-08-02T12:00:00Z"}
    ).json()["data"]["id"]
    client.post(f"/api/cluster-runs/{run_id}/apply")
    issue = client.get("/api/issues", params={"report_date": report_date}).json()["data"]["issues"][0]

    edited = client.patch(
        f"/api/issues/{issue['id']}",
        json={
            "editorTitle": "담당자 확정 제목",
            "editorStatus": "ongoing",
            "editorPriority": "required",
            "articleId": second,
            "membershipAction": "remove",
        },
    )
    assert edited.status_code == 200
    assert edited.json()["data"]["articleIds"] == [first]

    rerun = client.post(
        "/api/cluster-runs", json={"reportDate": report_date, "asOf": "2026-08-02T13:00:00Z"}
    ).json()["data"]
    assert issue["id"] == rerun["proposal"][0]["existingIssueId"]
    assert issue["id"] in rerun["diff"]["preservedEditorOverrides"]
    client.post(f"/api/cluster-runs/{rerun['id']}/apply")

    preserved = client.get("/api/issues", params={"report_date": report_date}).json()["data"]["issues"][0]
    assert preserved["id"] == issue["id"]
    assert preserved["effectiveTitle"] == "담당자 확정 제목"
    assert preserved["effectiveStatus"] == "ongoing"
    assert preserved["effectivePriority"] == "required"
    assert preserved["articleIds"] == [first]
    assert preserved["membershipOverrides"] == [{"article_id": second, "action": "remove"}]


def test_cluster_apply_rejects_stale_proposal_and_final_briefing():
    report_date = "2026-08-03"
    _create_briefing(report_date)
    _create_article(
        report_date, "stale-1", "전주 아파트 대규모 정전 발생", "연합뉴스",
        "2026-08-03T05:00:00Z",
    )
    stale_run = client.post(
        "/api/cluster-runs", json={"reportDate": report_date, "asOf": "2026-08-03T12:00:00Z"}
    ).json()["data"]
    _create_article(
        report_date, "stale-2", "전주 완산구 아파트 정전 발생", "KBS",
        "2026-08-03T08:00:00Z",
    )
    stale = client.post(f"/api/cluster-runs/{stale_run['id']}/apply")
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "CLUSTER_RUN_STALE"

    fresh_run = client.post(
        "/api/cluster-runs", json={"reportDate": report_date, "asOf": "2026-08-03T12:00:00Z"}
    ).json()["data"]
    connection = get_connection()
    try:
        with connection:
            connection.execute("UPDATE briefings SET status = 'final' WHERE report_date = ?", (report_date,))
    finally:
        connection.close()
    blocked = client.post(f"/api/cluster-runs/{fresh_run['id']}/apply")
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "BRIEFING_FINALIZED"


def test_briefing_issue_patch_checks_revision_and_persists_state():
    report_date = "2026-08-04"
    _create_briefing(report_date)
    _create_article(
        report_date, "briefing-issue", "전주 아파트 정전 발생", "연합뉴스",
        "2026-08-04T05:00:00Z",
    )
    run = client.post(
        "/api/cluster-runs", json={"reportDate": report_date, "asOf": "2026-08-04T12:00:00Z"}
    ).json()["data"]
    client.post(f"/api/cluster-runs/{run['id']}/apply")
    issue_id = client.get(
        "/api/issues", params={"report_date": report_date}
    ).json()["data"]["issues"][0]["id"]
    briefing = client.get(f"/api/briefings/{report_date}").json()["data"]
    patched = client.patch(
        f"/api/briefings/{report_date}/issues/{issue_id}",
        json={"expectedRevision": briefing["revision"], "selected": True, "note": "이슈 메모"},
    )
    assert patched.status_code == 200
    assert patched.json()["data"]["revision"] == briefing["revision"] + 1
    stale = client.patch(
        f"/api/briefings/{report_date}/issues/{issue_id}",
        json={"expectedRevision": briefing["revision"], "starred": True},
    )
    assert stale.status_code == 409
