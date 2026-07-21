import threading

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.repositories import article_repository as article_repo
from backend.app.repositories.database import get_connection
from backend.app.services.extraction.article_body import BodyFetchResult
from backend.app.services.extraction import evidence_quality
from backend.app.services.analysis_markdown import service as markdown_service

client = TestClient(app)


def _setup_issue(report_date: str, count: int = 4) -> tuple[dict, list[str]]:
    assert client.put(
        f"/api/briefings/{report_date}", json={"expectedRevision": 0, "patch": {}}
    ).status_code == 200
    article_ids = []
    titles = [
        "전주 변전소 침수 대비 안전점검 결과 발표",
        "제주 태양광 설비 사용전검사 제도 개선",
        "서울 데이터센터 비상전원 안전관리 대책",
        "부산 전기차 충전시설 화재 예방 현장점검",
    ]
    for index in range(count):
        response = client.post(
            "/api/articles",
            json={
                "reportDate": report_date,
                "title": titles[index],
                "source": f"테스트언론{index}",
                "url": f"https://evidence.example.com/{report_date}/{index}",
                "pubDate": f"{report_date}T0{index}:00:00Z",
                "description": "관계기관은 전기설비 안전점검 결과와 피해 수치 및 후속 조치 계획을 발표했다고 밝혔다. " * 3,
                "category": "safety",
            },
        )
        assert response.status_code == 200
        article_ids.append(response.json()["data"]["id"])
    connection = get_connection()
    try:
        body = (
            "관계기관은 전기설비 30곳의 안전점검 결과와 피해 수치, 후속 조사 일정 및 "
            "재발 방지 대책을 공식 발표했다고 밝혔다. " * 12
        )
        with connection:
            for article_id in article_ids[:-1]:
                article_repo.update_article_body(
                    connection, article_id, body_text=body,
                    body_status="full_text", body_error="",
                )
    finally:
        connection.close()
    revision = client.get(f"/api/briefings/{report_date}").json()["data"]["revision"]
    grouped = client.post(
        "/api/issues/manual-group",
        json={
            "reportDate": report_date,
            "articleIds": article_ids,
            "expectedRevision": revision,
        },
    )
    assert grouped.status_code == 200, grouped.json()
    return grouped.json()["data"]["issue"], article_ids


def test_issue_evidence_roles_quality_limits_and_revision_are_persisted():
    issue, article_ids = _setup_issue("2096-09-01")
    assert issue["representativeArticleId"] in article_ids[:-1]
    listed = client.get(f"/api/issues/{issue['id']}/articles")
    assert listed.status_code == 200
    articles = listed.json()["data"]["articles"]
    assert len(articles) == 4
    by_id = {item["articleId"]: item for item in articles}
    assert all(by_id[article_id]["cleanedCharacterCount"] > 500 for article_id in article_ids[:3])
    assert by_id[article_ids[-1]]["extractionStatus"] == "not_attempted"
    assert by_id[article_ids[-1]]["analysisEligible"] is False

    patched = client.patch(
        f"/api/issues/{issue['id']}/evidence",
        json={
            "expectedRevision": 0,
            "representativeArticleId": article_ids[1],
            "supplementalArticleIds": [article_ids[2]],
            "excludedArticleIds": [article_ids[3]],
        },
    )
    assert patched.status_code == 200
    data = patched.json()["data"]
    assert data["representativeArticleId"] == article_ids[1]
    assert data["manualRepresentative"] is True
    assert data["evidenceRevision"] == 1
    assert {item["articleId"]: item["role"] for item in data["articles"]} == {
        article_ids[0]: "related",
        article_ids[1]: "representative",
        article_ids[2]: "supplemental",
        article_ids[3]: "excluded",
    }

    stale = client.patch(
        f"/api/issues/{issue['id']}/evidence",
        json={"expectedRevision": 0, "representativeArticleId": article_ids[0]},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "ISSUE_EVIDENCE_REVISION_CONFLICT"

    ineligible = client.patch(
        f"/api/issues/{issue['id']}/evidence",
        json={
            "expectedRevision": 1,
            "representativeArticleId": article_ids[3],
            "excludedArticleIds": [],
        },
    )
    assert ineligible.status_code == 409
    assert ineligible.json()["error"]["code"] == "ARTICLE_BODY_UNAVAILABLE"

    too_many = client.patch(
        f"/api/issues/{issue['id']}/evidence",
        json={
            "expectedRevision": 1,
            "representativeArticleId": article_ids[1],
            "supplementalArticleIds": [article_ids[0], article_ids[2], article_ids[3]],
        },
    )
    assert too_many.status_code == 409
    assert too_many.json()["error"]["code"] == "SUPPLEMENTAL_ARTICLE_LIMIT_EXCEEDED"

    reloaded = client.get("/api/issues", params={"report_date": "2096-09-01"})
    saved = next(item for item in reloaded.json()["data"]["issues"] if item["id"] == issue["id"])
    assert saved["manualRepresentativeArticleId"] == article_ids[1]
    assert saved["manualSupplementalArticleIds"] == [article_ids[2]]
    assert saved["manualExcludedArticleIds"] == [article_ids[3]]

    run = client.post(
        "/api/cluster-runs",
        json={"reportDate": "2096-09-01", "asOf": "2096-09-01T12:00:00Z"},
    ).json()["data"]
    assert client.post(f"/api/cluster-runs/{run['id']}/apply").status_code == 200
    regrouped = client.get("/api/issues", params={"report_date": "2096-09-01"}).json()["data"]["issues"]
    preserved = next(item for item in regrouped if item["id"] == issue["id"])
    assert preserved["manualRepresentativeArticleId"] == article_ids[1]
    assert preserved["manualSupplementalArticleIds"] == [article_ids[2]]
    assert preserved["manualExcludedArticleIds"] == [article_ids[3]]


def test_markdown_uses_only_confirmed_representative_and_supplemental():
    issue, article_ids = _setup_issue("2096-10-02")
    patched = client.patch(
        f"/api/issues/{issue['id']}/evidence",
        json={
            "expectedRevision": 0,
            "representativeArticleId": article_ids[1],
            "supplementalArticleIds": [article_ids[2]],
            "excludedArticleIds": [article_ids[3]],
        },
    )
    assert patched.status_code == 200
    content = markdown_service.generate(
        get_connection, "2096-10-02", allow_network=False
    ).content
    assert f"기사 ID: `{article_ids[1]}`" in content
    assert f"기사 ID: `{article_ids[2]}`" in content
    assert f"기사 ID: `{article_ids[0]}`" not in content
    assert f"기사 ID: `{article_ids[3]}`" not in content
    assert "근거 역할: 대표기사" in content
    assert "근거 역할: 보조근거" in content


def test_reextract_updates_quality_and_enables_evidence_selection(monkeypatch):
    issue, article_ids = _setup_issue("2096-11-03", count=2)
    target = article_ids[-1]
    full_body = (
        "정부는 전기설비 안전점검 40곳의 결과와 후속 일정, 피해 수치 및 재발 방지 계획을 "
        "관계기관과 함께 발표했다고 밝혔다. " * 12
    )
    monkeypatch.setattr(
        "backend.app.services.analysis_markdown.service.fetch_article_body_with_retries",
        lambda url, **kwargs: BodyFetchResult(
            full_body, "success_full", "", url, ({"stage": "article_page", "status": "success"},)
        ),
    )
    response = client.post(f"/api/articles/{target}/reextract")
    assert response.status_code == 200
    quality = response.json()["data"]
    assert quality["extractionStatus"] == "success_full"
    assert quality["analysisEligible"] is True
    assert quality["contentQualityScore"] >= 75

    latest = client.get(f"/api/issues/{issue['id']}/articles").json()["data"]
    assert next(item for item in latest["articles"] if item["articleId"] == target)["analysisEligible"] is True
    selected = client.patch(
        f"/api/issues/{issue['id']}/evidence",
        json={"expectedRevision": 0, "representativeArticleId": target},
    )
    assert selected.status_code == 200
    assert selected.json()["data"]["representativeArticleId"] == target
    regenerated = markdown_service.generate(
        get_connection, "2096-11-03", allow_network=False
    ).content
    assert f"기사 ID: `{target}`" in regenerated


def test_reextract_all_issue_articles_runs_concurrently_and_scores_each_body(monkeypatch):
    issue, article_ids = _setup_issue("2096-11-04", count=3)
    connection = get_connection()
    try:
        with connection:
            connection.executemany(
                "UPDATE articles SET body_text = '', body_status = 'missing' WHERE id = ?",
                [(article_id,) for article_id in article_ids],
            )
    finally:
        connection.close()

    barrier = threading.Barrier(len(article_ids))
    worker_ids: set[int] = set()
    worker_lock = threading.Lock()
    full_body = (
        "관계기관은 전기설비 40곳의 안전점검 결과와 후속 일정, 피해 수치 및 재발 방지 계획을 "
        "관계기관과 함께 발표했다고 밝혔다. " * 12
    )

    def fetch_body(url, **kwargs):  # noqa: ARG001
        with worker_lock:
            worker_ids.add(threading.get_ident())
        barrier.wait(timeout=3)
        return BodyFetchResult(
            full_body,
            "success_full",
            "",
            url,
            ({"stage": "article_page", "status": "success"},),
        )

    monkeypatch.setattr(
        "backend.app.services.analysis_markdown.service.fetch_article_body_with_retries",
        fetch_body,
    )
    response = client.post(f"/api/issues/{issue['id']}/articles/reextract")
    assert response.status_code == 200, response.json()
    result = response.json()["data"]
    assert result["requestedCount"] == 3
    assert result["succeededCount"] == 3
    assert result["failedCount"] == 0
    assert len(worker_ids) == 3
    assert len(result["articles"]) == 3
    assert all(item["contentQualityScore"] >= 75 for item in result["articles"])
    assert all(item["cleanedText"] for item in result["articles"])


def test_reextract_all_issue_articles_rejects_unknown_issue():
    response = client.post("/api/issues/missing-issue/articles/reextract")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ISSUE_NOT_FOUND"


def test_reextract_all_issue_articles_preserves_successes_on_partial_failure(monkeypatch):
    issue, article_ids = _setup_issue("2096-11-05", count=3)
    before = client.get(f"/api/issues/{issue['id']}/articles").json()["data"]["articles"]
    previous_failed_text = next(
        item["cleanedText"] for item in before if item["articleId"] == article_ids[1]
    )
    connection = get_connection()
    try:
        with connection:
            connection.executemany(
                "UPDATE articles SET body_text = '', body_status = 'missing' WHERE id = ?",
                [(article_id,) for article_id in article_ids],
            )
    finally:
        connection.close()

    full_body = "전기설비 안전점검 결과와 후속 조치 계획을 공식 발표했다. " * 30

    def fetch_body(url, **kwargs):  # noqa: ARG001
        if url.endswith("/1"):
            raise RuntimeError("publisher timeout")
        return BodyFetchResult(
            full_body,
            "success_full",
            "",
            url,
            ({"stage": "article_page", "status": "success"},),
        )

    monkeypatch.setattr(
        "backend.app.services.analysis_markdown.service.fetch_article_body_with_retries",
        fetch_body,
    )
    response = client.post(f"/api/issues/{issue['id']}/articles/reextract")
    assert response.status_code == 200
    result = response.json()["data"]
    assert result["succeededCount"] == 2
    assert result["failedCount"] == 1
    assert result["failures"][0]["articleId"] == article_ids[1]
    by_id = {item["articleId"]: item for item in result["articles"]}
    assert by_id[article_ids[0]]["cleanedText"]
    assert by_id[article_ids[2]]["cleanedText"]
    assert by_id[article_ids[1]]["cleanedText"] == previous_failed_text


def test_markdown_export_repairs_missing_representative_after_body_refresh():
    report_date = "2096-11-06"
    issue, article_ids = _setup_issue(report_date, count=2)
    briefing = client.get(f"/api/briefings/{report_date}").json()["data"]
    selected = client.patch(
        f"/api/briefings/{report_date}/articles/{article_ids[0]}",
        json={"expectedRevision": briefing["revision"], "selected": True},
    )
    assert selected.status_code == 200
    connection = get_connection()
    try:
        with connection:
            connection.execute(
                "UPDATE issues SET auto_priority = 'required', representative_article_id = NULL WHERE id = ?",
                (issue["id"],),
            )
    finally:
        connection.close()

    response = client.post(f"/api/exports/{report_date}.md")
    assert response.status_code == 200, response.text
    repaired = client.get(f"/api/issues/{issue['id']}/articles").json()["data"]
    assert repaired["representativeArticleId"] in article_ids


def test_required_issue_without_representative_blocks_markdown():
    issue, article_ids = _setup_issue("2096-12-04", count=2)
    assert client.patch(
        f"/api/issues/{issue['id']}", json={"editorPriority": "required"}
    ).status_code == 200
    excluded = client.patch(
        f"/api/issues/{issue['id']}/evidence",
        json={
            "expectedRevision": 0,
            "representativeArticleId": None,
            "excludedArticleIds": article_ids,
        },
    )
    assert excluded.status_code == 200
    assert excluded.json()["data"]["representativeEvidenceMissing"] is True
    try:
        markdown_service.generate(get_connection, "2096-12-04", allow_network=False)
    except markdown_service.GenerationError as exc:
        assert exc.code == "REQUIRED_ARTICLE_EVIDENCE_MISSING"
        assert exc.details[0]["issueId"] == issue["id"]
    else:
        raise AssertionError("필수 이슈의 대표 근거가 없으면 MD 생성이 차단돼야 합니다.")


def test_disabled_publisher_is_not_analysis_eligible(monkeypatch):
    config = evidence_quality.load_config()
    monkeypatch.setattr(
        evidence_quality,
        "load_config",
        lambda: {**config, "disabled_publishers": ["테스트언론0"]},
    )
    issue, article_ids = _setup_issue("2097-01-05", count=2)
    evidence = client.get(f"/api/issues/{issue['id']}/articles").json()["data"]
    blocked = next(item for item in evidence["articles"] if item["articleId"] == article_ids[0])
    assert blocked["analysisEligible"] is False
    assert blocked["qualityGrade"] == "unavailable"
    assert "언론사 상태가 분석 제외입니다" in blocked["qualityReasons"]
