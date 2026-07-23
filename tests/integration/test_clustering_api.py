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

    collection_feature = client.get("/js/features/collection.js")
    assert collection_feature.status_code == 200
    assert "AUTO_CLUSTER_SIMILARITY_THRESHOLD = 0.15" in collection_feature.text
    assert "automaticallyRecluster()" in collection_feature.text
    assert "createClusterRun(state.date, AUTO_CLUSTER_SIMILARITY_THRESHOLD)" in collection_feature.text
    assert "applyClusterRun(proposed.data.id)" in collection_feature.text
    assert "setSearchProgress(72" in collection_feature.text
    assert "finishSearchProgress(true)" in collection_feature.text

    api_client = client.get("/js/api/client.js")
    assert api_client.status_code == 200
    assert "CLUSTER_RUN_TIMEOUT_MS = 120000" in api_client.text
    assert "}, CLUSTER_RUN_TIMEOUT_MS);" in api_client.text

    issues_feature = client.get("/js/features/issues.js")
    assert issues_feature.status_code == 200
    assert "issue.selected" in issues_feature.text
    assert "article.topIssue" in issues_feature.text
    assert "visibleRepresentative" in issues_feature.text
    assert "issue.editorTitle || visibleRepresentative?.title" in issues_feature.text
    assert "MAX_TOP_ISSUES = 6" in issues_feature.text
    assert "categoryChips" in issues_feature.text
    assert "getTopIssueEntries" in issues_feature.text
    assert 'data-action="move-top-issue"' in issues_feature.text
    assert "autoReviewScore" not in issues_feature.text
    assert "sourceCount" not in issues_feature.text

    articles_feature = client.get("/js/features/articles.js")
    assert articles_feature.status_code == 200
    assert "renderMediaGroups" in articles_feature.text
    assert "카드의 관련기사 수와 펼침 목록은 현재 화면 필터가 아니라 이슈 전체 membership을 따른다" in articles_feature.text
    assert "renderArticleCard(representative.article, issue, managementMembers)" in articles_feature.text
    assert "function relatedArticleCounts()" in articles_feature.text
    assert "(relatedCounts.get(b.id) || 0) - (relatedCounts.get(a.id) || 0)" in articles_feature.text
    assert "entries.sort((left, right) => left.position - right.position)" in articles_feature.text
    assert "renderRelatedArticle" in articles_feature.text
    assert "member.article.id === issue.representativeArticleId" in articles_feature.text
    assert 'data-action="set-representative"' in articles_feature.text
    assert 'data-action="toggle-supplemental"' in articles_feature.text
    assert 'data-action="reextract-all-bodies"' in articles_feature.text
    assert 'data-action="sort-related-quality"' in articles_feature.text
    assert "collapsedRepresentativePreviewKeys" in articles_feature.text
    assert "rightRepresentative - leftRepresentative" in articles_feature.text

    report_draft_feature = client.get("/js/features/report-draft.js")
    assert "const issuesResult = await api.listIssues(state.date)" in report_draft_feature.text
    assert "renderArticles();" in report_draft_feature.text
    assert 'quality.role === "representative"' in articles_feature.text
    assert "본문 충실도순" in articles_feature.text
    assert "전체 본문 다시 추출" in articles_feature.text
    assert "reextractIssueArticles(issueId)" in articles_feature.text
    assert "Math.random()" not in articles_feature.text
    assert "관련기사 ${relatedCount}건" in articles_feature.text
    assert "member.article.id !== a.id" in articles_feature.text
    assert "오류 사유" in report_draft_feature.text
    assert "언론사 ${escapeHtml(article.source" in report_draft_feature.text
    assert "제목을 확인할 수 없는 기사" in report_draft_feature.text
    assert '"REQUIRED_ARTICLE_EVIDENCE_MISSING"].includes(error.code)' in report_draft_feature.text
    assert "대표 근거 기사를 다시 지정해야 하는 필수 보고 이슈" in report_draft_feature.text
    assert "setEvidenceValidationFailures(error.details?.failedArticles || [])" in report_draft_feature.text
    assert "MD 전체 차단" in articles_feature.text
    assert "badge-evidence-error" in articles_feature.text
    assert '<details class="related-articles"' in articles_feature.text
    assert 'data-action="top-issue"' in articles_feature.text
    assert 'data-action="article-top-issue"' in articles_feature.text
    assert 'data-action="direct-coverage"' in articles_feature.text
    assert 'data-action="remove-related"' in articles_feature.text
    assert "removeIssueArticle" in articles_feature.text
    assert "related-include-check" in articles_feature.text
    assert "handleTopIssuesClick" in articles_feature.text
    assert "moveTopIssue" in articles_feature.text
    assert "탑이슈 배치 순서를 저장했습니다" in articles_feature.text
    assert "공사 직접 보도 태그를 수동 해제하고 브리핑 기사로 반영합니다" in articles_feature.text
    assert "topIssueTagCount() >= MAX_TOP_ISSUES" in articles_feature.text
    assert 'issue?.effectiveTitle || ""' in articles_feature.text
    assert 'data-action="group-picker-select"' in articles_feature.text
    assert "openManualGroupPicker" in articles_feature.text
    assert "createManualIssueGroup" in articles_feature.text
    assert 'id="manualGroupModeBtn"' in page.text
    assert 'id="manualGroupOverlay"' in page.text
    assert 'id="manualGroupCancelBtn"' in page.text
    assert "기존 묶음을 선택하면 그 안의 기사 전체가 함께 합쳐집니다" in page.text
    assert "buildManualGroupPickerEntries" in articles_feature.text
    assert "issue.articleIds" in articles_feature.text
    assert 'data-action="remove-top-issue"' in issues_feature.text


def _create_briefing(report_date: str) -> None:
    response = client.put(f"/api/briefings/{report_date}", json={"expectedRevision": 0, "patch": {}})
    assert response.status_code == 200


def _create_article(
    report_date: str,
    suffix: str,
    title: str,
    source: str,
    pub_date: str,
    *,
    category: str = "safety",
) -> str:
    response = client.post(
        "/api/articles",
        json={
            "reportDate": report_date,
            "title": title,
            "source": source,
            "url": f"https://cluster.example.com/{suffix}",
            "pubDate": pub_date,
            "description": "전주 완산구 아파트 변압기 고장으로 주민들이 불편을 겪었다",
            "category": category,
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


def test_government_press_release_observations_are_not_auto_grouped():
    report_date = "2027-12-31"
    _create_briefing(report_date)
    first = _create_article(
        report_date,
        "government-1",
        "정부, 블록체인 기반 예금토큰 민간 인프라 확산",
        "과학기술정보통신부",
        "2027-12-31T05:00:00Z",
    )
    second = _create_article(
        report_date,
        "government-2",
        "정부, 블록체인 기반 디지털 산업 인프라 확산",
        "문화체육관광부",
        "2027-12-31T06:00:00Z",
    )
    connection = get_connection()
    try:
        with connection:
            connection.execute(
                "UPDATE article_observations SET provider = '정책브리핑 API' "
                "WHERE article_id IN (?, ?)",
                (first, second),
            )
    finally:
        connection.close()

    proposed = client.post(
        "/api/cluster-runs",
        json={
            "reportDate": report_date,
            "asOf": "2027-12-31T12:00:00Z",
            "similarityThreshold": 0.15,
        },
    )

    assert proposed.status_code == 200
    proposal = proposed.json()["data"]["proposal"]
    assert {frozenset(issue["articleIds"]) for issue in proposal} == {
        frozenset({first}),
        frozenset({second}),
    }


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


def test_briefing_scoped_related_article_remove_bumps_revision_and_preserves_article_state():
    report_date = "2026-08-12"
    _create_briefing(report_date)
    first = _create_article(
        report_date, "manual-remove-1", "전주 아파트 대규모 정전 발생 500세대 불편", "연합뉴스",
        "2026-08-12T05:00:00Z",
    )
    second = _create_article(
        report_date, "manual-remove-2", "전주 완산구 아파트 정전…500가구 전력 끊겨", "KBS",
        "2026-08-12T08:00:00Z",
    )
    run_id = client.post(
        "/api/cluster-runs", json={"reportDate": report_date, "asOf": "2026-08-12T12:00:00Z"}
    ).json()["data"]["id"]
    client.post(f"/api/cluster-runs/{run_id}/apply")
    issue = client.get("/api/issues", params={"report_date": report_date}).json()["data"]["issues"][0]
    revision = client.get(f"/api/briefings/{report_date}").json()["data"]["revision"]
    selected = client.patch(
        f"/api/briefings/{report_date}/articles/{second}",
        json={"expectedRevision": revision, "selected": True, "note": "선정 상태 유지"},
    )
    revision = selected.json()["data"]["revision"]

    removed = client.patch(
        f"/api/briefings/{report_date}/issues/{issue['id']}",
        json={
            "expectedRevision": revision,
            "articleId": second,
            "membershipAction": "remove",
        },
    )
    assert removed.status_code == 200
    assert removed.json()["data"]["revision"] == revision + 1
    remaining = client.get("/api/issues", params={"report_date": report_date}).json()["data"]["issues"][0]
    assert remaining["articleIds"] == [first]
    articles = client.get("/api/articles", params={"report_date": report_date}).json()["data"]["articles"]
    saved = next(item for item in articles if item["id"] == second)
    assert saved["included"] is True
    assert saved["note"] == "선정 상태 유지"


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


def test_direct_coverage_is_auto_tagged_excluded_and_manual_override_is_preserved():
    report_date = "2026-08-18"
    _create_briefing(report_date)
    article_id = _create_article(
        report_date,
        "direct-coverage",
        "한국전기안전공사 해외사업 성과와 전기안전 수출 확대",
        "전기신문",
        "2026-08-18T05:00:00Z",
        category="kesco_direct",
    )
    initial_article = client.get(
        "/api/articles", params={"report_date": report_date}
    ).json()["data"]["articles"][0]
    assert initial_article["included"] is False
    assert initial_article["autoDirectCoverage"] is True
    assert initial_article["editorDirectCoverage"] is None
    assert initial_article["directCoverage"] is True

    run = client.post(
        "/api/cluster-runs",
        json={"reportDate": report_date, "asOf": "2026-08-18T12:00:00Z"},
    ).json()["data"]
    assert client.post(f"/api/cluster-runs/{run['id']}/apply").status_code == 200

    issue = client.get(
        "/api/issues", params={"report_date": report_date}
    ).json()["data"]["issues"][0]
    assert issue["autoDirectCoverage"] is True
    assert issue["editorDirectCoverage"] is None
    assert issue["directCoverage"] is True
    article = client.get(
        "/api/articles", params={"report_date": report_date}
    ).json()["data"]["articles"][0]
    assert article["included"] is False
    assert article["topIssue"] is False

    revision = client.get(f"/api/briefings/{report_date}").json()["data"]["revision"]
    blocked = client.patch(
        f"/api/briefings/{report_date}/articles/{article_id}",
        json={"expectedRevision": revision, "selected": True},
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "DIRECT_COVERAGE_NOT_SELECTABLE"
    blocked_top = client.patch(
        f"/api/briefings/{report_date}/issues/{issue['id']}",
        json={"expectedRevision": revision, "selected": True},
    )
    assert blocked_top.status_code == 409
    assert blocked_top.json()["error"]["code"] == "DIRECT_COVERAGE_NOT_SELECTABLE"

    overridden = client.patch(
        f"/api/briefings/{report_date}/issues/{issue['id']}",
        json={"expectedRevision": revision, "directCoverage": False},
    )
    assert overridden.status_code == 200
    revision = overridden.json()["data"]["revision"]
    issue = client.get(
        "/api/issues", params={"report_date": report_date}
    ).json()["data"]["issues"][0]
    assert issue["editorDirectCoverage"] is False
    assert issue["directCoverage"] is False

    selected = client.patch(
        f"/api/briefings/{report_date}/articles/{article_id}",
        json={"expectedRevision": revision, "selected": True},
    )
    assert selected.status_code == 200
    revision = selected.json()["data"]["revision"]

    rerun = client.post(
        "/api/cluster-runs",
        json={"reportDate": report_date, "asOf": "2026-08-18T13:00:00Z"},
    ).json()["data"]
    assert client.post(f"/api/cluster-runs/{rerun['id']}/apply").status_code == 200
    preserved = client.get(
        "/api/issues", params={"report_date": report_date}
    ).json()["data"]["issues"][0]
    assert preserved["editorDirectCoverage"] is False
    assert preserved["directCoverage"] is False
    assert client.get(
        "/api/articles", params={"report_date": report_date}
    ).json()["data"]["articles"][0]["included"] is True

    retagged = client.patch(
        f"/api/briefings/{report_date}/issues/{preserved['id']}",
        json={"expectedRevision": revision, "directCoverage": True},
    )
    assert retagged.status_code == 200
    assert client.get(
        "/api/articles", params={"report_date": report_date}
    ).json()["data"]["articles"][0]["included"] is False


def test_article_selection_can_clear_auto_direct_coverage_in_same_mutation():
    report_date = "2026-08-29"
    _create_briefing(report_date)
    article_id = _create_article(
        report_date,
        "direct-select",
        "한국전기안전공사 현안 보도 담당자 브리핑 선정",
        "전기신문",
        "2026-08-29T05:00:00Z",
        category="kesco_direct",
    )
    run = client.post(
        "/api/cluster-runs",
        json={"reportDate": report_date, "asOf": "2026-08-29T12:00:00Z"},
    ).json()["data"]
    assert client.post(f"/api/cluster-runs/{run['id']}/apply").status_code == 200
    revision = client.get(f"/api/briefings/{report_date}").json()["data"]["revision"]

    selected = client.patch(
        f"/api/briefings/{report_date}/articles/{article_id}",
        json={
            "expectedRevision": revision,
            "selected": True,
            "directCoverage": False,
        },
    )
    assert selected.status_code == 200
    article = client.get(
        "/api/articles", params={"report_date": report_date}
    ).json()["data"]["articles"][0]
    assert article["included"] is True
    assert article["editorDirectCoverage"] is False
    assert article["directCoverage"] is False
    issue = client.get(
        "/api/issues", params={"report_date": report_date}
    ).json()["data"]["issues"][0]
    assert issue["editorDirectCoverage"] is False
    assert issue["directCoverage"] is False


def test_ungrouped_direct_coverage_manual_override_survives_first_clustering():
    report_date = "2026-08-19"
    _create_briefing(report_date)
    article_id = _create_article(
        report_date,
        "direct-standalone",
        "KESCO 해외사업 성과와 전기안전 수출 확대",
        "전기신문",
        "2026-08-19T05:00:00Z",
        category="kesco_direct",
    )
    article = client.get(
        "/api/articles", params={"report_date": report_date}
    ).json()["data"]["articles"][0]
    assert article["directCoverage"] is True
    assert article["included"] is False

    revision = client.get(f"/api/briefings/{report_date}").json()["data"]["revision"]
    overridden = client.patch(
        f"/api/briefings/{report_date}/articles/{article_id}",
        json={"expectedRevision": revision, "directCoverage": False},
    )
    assert overridden.status_code == 200
    revision = overridden.json()["data"]["revision"]
    selected = client.patch(
        f"/api/briefings/{report_date}/articles/{article_id}",
        json={"expectedRevision": revision, "selected": True},
    )
    assert selected.status_code == 200

    run = client.post(
        "/api/cluster-runs",
        json={"reportDate": report_date, "asOf": "2026-08-19T12:00:00Z"},
    ).json()["data"]
    assert client.post(f"/api/cluster-runs/{run['id']}/apply").status_code == 200
    issue = client.get(
        "/api/issues", params={"report_date": report_date}
    ).json()["data"]["issues"][0]
    assert issue["autoDirectCoverage"] is True
    assert issue["editorDirectCoverage"] is False
    assert issue["directCoverage"] is False
    article = client.get(
        "/api/articles", params={"report_date": report_date}
    ).json()["data"]["articles"][0]
    assert article["included"] is True


def test_issue_review_stars_are_ranked_and_editor_override_is_preserved():
    report_date = "2026-08-14"
    _create_briefing(report_date)
    _create_article(
        report_date, "review-star", "한국전기안전공사 압수수색 관련 사실 확인", "연합뉴스",
        "2026-08-14T05:00:00Z",
    )
    run = client.post(
        "/api/cluster-runs", json={"reportDate": report_date, "asOf": "2026-08-14T06:00:00Z"}
    ).json()["data"]
    assert run["proposal"][0]["autoReviewRank"] == 1
    assert 1 <= run["proposal"][0]["autoReviewStars"] <= 5
    assert "urgency" in run["proposal"][0]["reviewReasons"]["components"]
    client.post(f"/api/cluster-runs/{run['id']}/apply")
    issue = client.get("/api/issues", params={"report_date": report_date}).json()["data"]["issues"][0]
    briefing = client.get(f"/api/briefings/{report_date}").json()["data"]
    patched = client.patch(
        f"/api/briefings/{report_date}/issues/{issue['id']}",
        json={"expectedRevision": briefing["revision"], "editorReviewStars": 2},
    )
    assert patched.status_code == 200
    overridden = client.get("/api/issues", params={"report_date": report_date}).json()["data"]["issues"][0]
    assert overridden["editorReviewStars"] == 2
    assert overridden["effectiveReviewStars"] == 2

    rerun = client.post(
        "/api/cluster-runs", json={"reportDate": report_date, "asOf": "2026-08-14T07:00:00Z"}
    ).json()["data"]
    client.post(f"/api/cluster-runs/{rerun['id']}/apply")
    preserved = client.get("/api/issues", params={"report_date": report_date}).json()["data"]["issues"][0]
    assert preserved["editorReviewStars"] == 2
    assert preserved["effectiveReviewStars"] == 2


def test_individual_article_top_issue_tag_selects_article_and_untag_keeps_selection():
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
    deselected = client.patch(
        f"/api/briefings/{report_date}/articles/{article_id}",
        json={"expectedRevision": briefing["revision"], "selected": False},
    )
    assert deselected.status_code == 200
    patched = client.patch(
        f"/api/briefings/{report_date}/articles/{article_id}",
        json={"expectedRevision": deselected.json()["data"]["revision"], "topIssue": True},
    )
    assert patched.status_code == 200

    articles = client.get(
        "/api/articles", params={"report_date": report_date}
    ).json()["data"]["articles"]
    assert articles[0]["topIssue"] is True
    assert articles[0]["starred"] is False
    assert articles[0]["included"] is True
    untagged = client.patch(
        f"/api/briefings/{report_date}/articles/{article_id}",
        json={"expectedRevision": patched.json()["data"]["revision"], "topIssue": False},
    )
    assert untagged.status_code == 200
    article = client.get(
        "/api/articles", params={"report_date": report_date}
    ).json()["data"]["articles"][0]
    assert article["topIssue"] is False
    assert article["included"] is True


def test_issue_top_tag_selects_clicked_article_and_untag_keeps_selection():
    report_date = "2026-08-20"
    _create_briefing(report_date)
    article_id = _create_article(
        report_date,
        "issue-top-select",
        "전기화재 예방 점검 확대",
        "지역일보",
        "2026-08-20T05:00:00Z",
    )
    run = client.post(
        "/api/cluster-runs",
        json={"reportDate": report_date, "asOf": "2026-08-20T12:00:00Z"},
    ).json()["data"]
    client.post(f"/api/cluster-runs/{run['id']}/apply")
    issue = client.get(
        "/api/issues", params={"report_date": report_date}
    ).json()["data"]["issues"][0]
    revision = client.get(f"/api/briefings/{report_date}").json()["data"]["revision"]
    deselected = client.patch(
        f"/api/briefings/{report_date}/articles/{article_id}",
        json={"expectedRevision": revision, "selected": False},
    ).json()["data"]
    tagged = client.patch(
        f"/api/briefings/{report_date}/issues/{issue['id']}",
        json={
            "expectedRevision": deselected["revision"],
            "selected": True,
            "articleId": article_id,
        },
    )
    assert tagged.status_code == 200
    article = client.get(
        "/api/articles", params={"report_date": report_date}
    ).json()["data"]["articles"][0]
    assert article["included"] is True
    untagged = client.patch(
        f"/api/briefings/{report_date}/issues/{issue['id']}",
        json={"expectedRevision": tagged.json()["data"]["revision"], "selected": False},
    )
    assert untagged.status_code == 200
    article = client.get(
        "/api/articles", params={"report_date": report_date}
    ).json()["data"]["articles"][0]
    assert article["included"] is True


def test_article_top_tag_maps_to_only_one_overlapping_issue_and_can_be_cleared():
    report_date = "2026-08-21"
    _create_briefing(report_date)
    article_id = _create_article(
        report_date,
        "overlapping-top-issue",
        "ESS 배터리 화재 안전대책 점검",
        "안전일보",
        "2026-08-21T05:00:00Z",
    )
    now = "2026-08-21T06:00:00Z"
    older_issue_id = "overlapping-issue-selected"
    newer_issue_id = "overlapping-issue-newer"
    connection = get_connection()
    try:
        briefing_id = connection.execute(
            "SELECT id FROM briefings WHERE report_date = ?", (report_date,)
        ).fetchone()["id"]
        for index, issue_id in enumerate((older_issue_id, newer_issue_id), start=1):
            run_id = f"overlapping-run-{index}"
            connection.execute(
                """
                INSERT INTO cluster_runs (
                    id, report_date, status, input_signature, proposal_json, diff_json,
                    algorithm_version, created_at, applied_at
                ) VALUES (?, ?, 'applied', ?, '[]', '{}', 'test', ?, ?)
                """,
                (run_id, report_date, f"signature-{index}", now, now),
            )
            connection.execute(
                """
                INSERT INTO issues (
                    id, representative_article_id, auto_title, spread_score,
                    direct_mention, needs_review, last_cluster_run_id, created_at, updated_at
                ) VALUES (?, ?, ?, 0, 0, 0, ?, ?, ?)
                """,
                (issue_id, article_id, f"겹친 그룹 {index}", run_id, now, now),
            )
            connection.execute(
                """
                INSERT INTO issue_auto_articles (
                    issue_id, article_id, cluster_run_id, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (issue_id, article_id, run_id, now),
            )
        connection.execute(
            """
            INSERT INTO briefing_issues (
                briefing_id, issue_id, selected, starred, note, sort_order,
                created_at, updated_at
            ) VALUES (?, ?, 1, 0, NULL, 0, ?, ?)
            """,
            (briefing_id, older_issue_id, now, now),
        )
        connection.execute(
            """
            UPDATE briefing_articles
            SET selected = 1, top_issue = 1, updated_at = ?
            WHERE briefing_id = ? AND article_id = ?
            """,
            (now, briefing_id, article_id),
        )
        connection.commit()
    finally:
        connection.close()

    issues = client.get(
        "/api/issues", params={"report_date": report_date}
    ).json()["data"]["issues"]
    assert {issue["id"] for issue in issues if issue["selected"]} == {older_issue_id}

    revision = client.get(f"/api/briefings/{report_date}").json()["data"]["revision"]
    cleared = client.patch(
        f"/api/briefings/{report_date}/issues/{older_issue_id}",
        json={"expectedRevision": revision, "selected": False},
    )
    assert cleared.status_code == 200
    after = client.get(
        "/api/issues", params={"report_date": report_date}
    ).json()["data"]["issues"]
    assert not any(issue["selected"] for issue in after)


def test_top_issues_allow_six_and_promote_article_tags_after_clustering():
    report_date = "2026-08-15"
    _create_briefing(report_date)
    article_ids = [
        _create_article(
            report_date,
            f"top-six-{index}",
            f"전기안전 점검 Top 이슈 후보 {index}",
            f"지역일보{index}",
            f"2026-08-15T0{index}:00:00Z",
        )
        for index in range(7)
    ]
    revision = client.get(f"/api/briefings/{report_date}").json()["data"]["revision"]

    for article_id in article_ids[:6]:
        response = client.patch(
            f"/api/briefings/{report_date}/articles/{article_id}",
            json={"expectedRevision": revision, "topIssue": True},
        )
        assert response.status_code == 200
        revision = response.json()["data"]["revision"]

    rejected = client.patch(
        f"/api/briefings/{report_date}/articles/{article_ids[6]}",
        json={"expectedRevision": revision, "topIssue": True},
    )
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "TOP_ISSUE_LIMIT_EXCEEDED"

    removed = client.patch(
        f"/api/briefings/{report_date}/articles/{article_ids[0]}",
        json={"expectedRevision": revision, "topIssue": False},
    )
    assert removed.status_code == 200
    replacement = client.patch(
        f"/api/briefings/{report_date}/articles/{article_ids[6]}",
        json={
            "expectedRevision": removed.json()["data"]["revision"],
            "topIssue": True,
        },
    )
    assert replacement.status_code == 200

    run = client.post(
        "/api/cluster-runs",
        json={"reportDate": report_date, "asOf": "2026-08-15T12:00:00Z"},
    ).json()["data"]
    assert client.post(f"/api/cluster-runs/{run['id']}/apply").status_code == 200
    issue = client.get(
        "/api/issues", params={"report_date": report_date}
    ).json()["data"]["issues"][0]
    assert issue["selected"] is True
    revision = replacement.json()["data"]["revision"]
    cleared_issue = client.patch(
        f"/api/briefings/{report_date}/issues/{issue['id']}",
        json={"expectedRevision": revision, "selected": False},
    )
    assert cleared_issue.status_code == 200
    articles = client.get(
        "/api/articles", params={"report_date": report_date}
    ).json()["data"]["articles"]
    assert not any(
        article["topIssue"]
        for article in articles
        if article["id"] in issue["articleIds"]
    )
    retagged_issue = client.patch(
        f"/api/briefings/{report_date}/issues/{issue['id']}",
        json={
            "expectedRevision": cleared_issue.json()["data"]["revision"],
            "selected": True,
        },
    )
    assert retagged_issue.status_code == 200


def test_hidden_selected_issue_does_not_consume_visible_top_issue_slot():
    report_date = "2026-08-16"
    _create_briefing(report_date)
    first = _create_article(
        report_date,
        "hidden-top-issue-1",
        "전주 완산구 아파트 정전 500세대 불편",
        "연합뉴스",
        "2026-08-16T01:00:00Z",
    )
    second = _create_article(
        report_date,
        "hidden-top-issue-2",
        "전주 아파트 대규모 정전 500가구 전력 중단",
        "KBS",
        "2026-08-16T02:00:00Z",
    )
    run = client.post(
        "/api/cluster-runs",
        json={"reportDate": report_date, "asOf": "2026-08-16T03:00:00Z"},
    ).json()["data"]
    assert client.post(f"/api/cluster-runs/{run['id']}/apply").status_code == 200
    issue = client.get(
        "/api/issues", params={"report_date": report_date}
    ).json()["data"]["issues"][0]
    assert set(issue["articleIds"]) == {first, second}

    revision = client.get(f"/api/briefings/{report_date}").json()["data"]["revision"]
    selected_issue = client.patch(
        f"/api/briefings/{report_date}/issues/{issue['id']}",
        json={
            "expectedRevision": revision,
            "selected": True,
            "articleId": first,
        },
    )
    assert selected_issue.status_code == 200
    revision = selected_issue.json()["data"]["revision"]

    standalone_ids = [
        _create_article(
            report_date,
            f"visible-top-{index}",
            f"서로 다른 지역 전기안전 현안 {index}",
            f"지역일보{index}",
            f"2026-08-16T{index + 4:02d}:00:00Z",
        )
        for index in range(6)
    ]
    for article_id in standalone_ids[:5]:
        tagged = client.patch(
            f"/api/briefings/{report_date}/articles/{article_id}",
            json={"expectedRevision": revision, "topIssue": True},
        )
        assert tagged.status_code == 200
        revision = tagged.json()["data"]["revision"]

    for article_id in (first, second):
        removed = client.patch(
            f"/api/briefings/{report_date}/issues/{issue['id']}",
            json={
                "expectedRevision": revision,
                "articleId": article_id,
                "membershipAction": "remove",
            },
        )
        assert removed.status_code == 200
        revision = removed.json()["data"]["revision"]

    visible_issues = client.get(
        "/api/issues", params={"report_date": report_date}
    ).json()["data"]["issues"]
    assert issue["id"] not in {item["id"] for item in visible_issues}

    replacement = client.patch(
        f"/api/briefings/{report_date}/articles/{standalone_ids[5]}",
        json={"expectedRevision": revision, "topIssue": True},
    )
    assert replacement.status_code == 200

    connection = get_connection()
    try:
        stale_state = connection.execute(
            """
            SELECT bi.selected
            FROM briefing_issues bi
            JOIN briefings b ON b.id = bi.briefing_id
            WHERE b.report_date = ? AND bi.issue_id = ?
            """,
            (report_date, issue["id"]),
        ).fetchone()
        assert stale_state is not None
        assert bool(stale_state["selected"]) is True
    finally:
        connection.close()


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
