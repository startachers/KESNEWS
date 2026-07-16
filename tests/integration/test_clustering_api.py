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
    assert 'min="15"' in page.text
    assert "15% · 가장 넓게 묶기" in page.text
    assert 'id="clusterRecalculateBtn"' in page.text

    feature = client.get("/js/features/clustering.js")
    assert feature.status_code == 200
    assert "createClusterRun(state.date, thresholdValue())" in feature.text
    assert "thresholdDirty" in feature.text
    assert "appliedThresholdPercent()" in feature.text
    assert "state.issues = issuesResult.data.issues" in feature.text
    assert "applyClusterRun(activeRun.id)" in feature.text

    api_client = client.get("/js/api/client.js")
    assert api_client.status_code == 200
    assert "CLUSTER_RUN_TIMEOUT_MS = 120000" in api_client.text
    assert "}, CLUSTER_RUN_TIMEOUT_MS);" in api_client.text

    issues_feature = client.get("/js/features/issues.js")
    assert issues_feature.status_code == 200
    assert "issue.selected" in issues_feature.text
    assert "article.topIssue" in issues_feature.text
    assert "같은 사건 기사" in issues_feature.text

    articles_feature = client.get("/js/features/articles.js")
    assert articles_feature.status_code == 200
    assert "renderMediaGroups" in articles_feature.text
    assert "unclustered.map(article => renderArticleCard(article))" in articles_feature.text
    assert "renderRelatedArticle" in articles_feature.text
    assert "representativeFor" in articles_feature.text
    assert "Math.random()" in articles_feature.text
    assert "관련 기사 ${relatedMembers.length}건" in articles_feature.text
    assert '<details class="related-articles"' in articles_feature.text
    assert 'data-action="top-issue"' in articles_feature.text
    assert 'data-action="article-top-issue"' in articles_feature.text
    assert 'data-action="group-picker-select"' in articles_feature.text
    assert "openManualGroupPicker" in articles_feature.text
    assert "createManualIssueGroup" in articles_feature.text
    assert 'id="manualGroupModeBtn"' in page.text
    assert 'id="manualGroupOverlay"' in page.text
    assert 'id="manualGroupCancelBtn"' in page.text
    assert "기존 묶음을 선택하면 그 안의 기사 전체가 함께 합쳐집니다" in page.text
    assert "buildManualGroupPickerEntries" in articles_feature.text
    assert "issue.articleIds" in articles_feature.text


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
            "similarityThreshold": 0.15,
        },
    )
    assert proposed.status_code == 200
    reasons = proposed.json()["data"]["proposal"][0]["autoReasons"]["clustering"]
    assert reasons == {"pairThreshold": 0.15, "minimumCrossScore": 0.15}

    invalid = client.post(
        "/api/cluster-runs",
        json={"reportDate": report_date, "similarityThreshold": 0.10},
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
    listed_issue = client.get(
        "/api/issues", params={"report_date": report_date}
    ).json()["data"]["issues"][0]
    assert listed_issue["selected"] is True
    assert listed_issue["note"] == "이슈 메모"
    stale = client.patch(
        f"/api/briefings/{report_date}/issues/{issue_id}",
        json={"expectedRevision": briefing["revision"], "starred": True},
    )
    assert stale.status_code == 409


def test_individual_article_top_issue_tag_persists_independently():
    report_date = "2026-08-06"
    _create_briefing(report_date)
    article_id = _create_article(
        report_date,
        "article-top-issue",
        "전기안전공사 집중호우 대비 현장 점검",
        "지역일보",
        "2026-08-06T05:00:00Z",
    )
    briefing = client.get(f"/api/briefings/{report_date}").json()["data"]
    patched = client.patch(
        f"/api/briefings/{report_date}/articles/{article_id}",
        json={"expectedRevision": briefing["revision"], "topIssue": True},
    )
    assert patched.status_code == 200

    articles = client.get(
        "/api/articles", params={"report_date": report_date}
    ).json()["data"]["articles"]
    assert articles[0]["topIssue"] is True
    assert articles[0]["starred"] is False
    # 직접 추가 기사의 기존 브리핑 선정 상태와는 독립적으로 저장된다.
    assert articles[0]["included"] is True


def test_manual_group_moves_articles_and_survives_reclustering():
    report_date = "2026-08-07"
    _create_briefing(report_date)
    first = _create_article(
        report_date, "manual-group-1", "전주 아파트 정전 발생 주민 불편", "연합뉴스",
        "2026-08-07T05:00:00Z",
    )
    second = _create_article(
        report_date, "manual-group-2", "전주 공동주택 전력 중단 주민 불편", "KBS",
        "2026-08-07T06:00:00Z",
    )
    third = _create_article(
        report_date, "manual-group-3", "전주 아파트 전력 중단 주민 불편", "지역일보",
        "2026-08-07T07:00:00Z",
    )
    briefing = client.get(f"/api/briefings/{report_date}").json()["data"]
    grouped = client.post(
        "/api/issues/manual-group",
        json={
            "reportDate": report_date,
            "articleIds": [first, second],
            "expectedRevision": briefing["revision"],
        },
    )
    assert grouped.status_code == 200
    manual_issue = grouped.json()["data"]["issue"]
    assert manual_issue["manualGroup"] is True
    assert set(manual_issue["articleIds"]) == {first, second}
    assert {item["action"] for item in manual_issue["membershipOverrides"]} == {"add"}

    rerun = client.post(
        "/api/cluster-runs",
        json={"reportDate": report_date, "asOf": "2026-08-07T12:00:00Z"},
    ).json()["data"]
    assert client.post(f"/api/cluster-runs/{rerun['id']}/apply").status_code == 200
    issues = client.get(
        "/api/issues", params={"report_date": report_date}
    ).json()["data"]["issues"]
    containing_both = [issue for issue in issues if {first, second}.issubset(issue["articleIds"])]
    assert len(containing_both) == 1
    assert containing_both[0]["manualGroup"] is True
    assert set(containing_both[0]["articleIds"]) == {first, second}
    assert any(third in issue["articleIds"] for issue in issues if not issue["manualGroup"])

    payload = client.get(f"/api/exports/{report_date}.json").json()["data"]
    assert any(issue["manualGroup"] for issue in payload["issues"])
    restored_date = "2026-08-08"
    imported = client.post(f"/api/exports/{restored_date}.json", json=payload)
    assert imported.status_code == 200
    assert imported.json()["data"]["issuesImported"] >= 1
    restored = client.get(
        "/api/issues", params={"report_date": restored_date}
    ).json()["data"]["issues"]
    restored_manual = next(issue for issue in restored if issue["manualGroup"])
    assert len(restored_manual["articleIds"]) == 2


def test_manual_groups_can_be_merged_without_leaving_old_memberships():
    report_date = "2026-08-09"
    _create_briefing(report_date)
    article_ids = [
        _create_article(
            report_date,
            f"merge-group-{index}",
            f"수동 묶음 병합 기사 {index}",
            f"매체 {index}",
            f"2026-08-09T0{index}:00:00Z",
        )
        for index in range(1, 5)
    ]
    revision = client.get(f"/api/briefings/{report_date}").json()["data"]["revision"]

    first_group = client.post(
        "/api/issues/manual-group",
        json={
            "reportDate": report_date,
            "articleIds": article_ids[:2],
            "expectedRevision": revision,
        },
    )
    assert first_group.status_code == 200
    revision = first_group.json()["data"]["revision"]
    second_group = client.post(
        "/api/issues/manual-group",
        json={
            "reportDate": report_date,
            "articleIds": article_ids[2:],
            "expectedRevision": revision,
        },
    )
    assert second_group.status_code == 200
    revision = second_group.json()["data"]["revision"]

    merged = client.post(
        "/api/issues/manual-group",
        json={
            "reportDate": report_date,
            "articleIds": article_ids,
            "expectedRevision": revision,
        },
    )
    assert merged.status_code == 200
    assert set(merged.json()["data"]["issue"]["articleIds"]) == set(article_ids)

    issues = client.get(
        "/api/issues", params={"report_date": report_date}
    ).json()["data"]["issues"]
    assert len(issues) == 1
    assert issues[0]["manualGroup"] is True
    assert set(issues[0]["articleIds"]) == set(article_ids)
