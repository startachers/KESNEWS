import csv
import io

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.repositories import press_release_repository as press_release_repo
from backend.app.repositories.database import get_connection
from backend.app.services.extraction.article_body import BodyFetchResult

client = TestClient(app)


def _setup_briefing_with_article(report_date: str):
    client.put(f"/api/briefings/{report_date}", json={"expectedRevision": 0, "patch": {"actionNote": "지시사항"}})
    created = client.post(
        "/api/articles",
        json={
            "reportDate": report_date,
            "title": "수출입 테스트 기사",
            "source": "테스트일보",
            "url": f"https://example.com/exports/{report_date}",
            "description": "설명",
            "category": "safety",
        },
    )
    article_id = created.json()["data"]["id"]
    briefing = client.get(f"/api/briefings/{report_date}").json()["data"]
    client.patch(
        f"/api/briefings/{report_date}/articles/{article_id}",
        json={"expectedRevision": briefing["revision"], "starred": True, "note": "중요 메모"},
    )
    return article_id


def test_json_export_missing_briefing_returns_404():
    response = client.get("/api/exports/2099-02-01.json")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "BRIEFING_NOT_FOUND"


def test_json_export_import_round_trip_preserves_selection_and_notes():
    report_date = "2025-02-01"
    _setup_briefing_with_article(report_date)

    exported = client.get(f"/api/exports/{report_date}.json")
    assert exported.status_code == 200
    payload = exported.json()["data"]
    assert payload["schemaVersion"] == 12
    assert payload["briefing"]["actionNote"] == "지시사항"
    assert len(payload["articles"]) == 1
    assert payload["articles"][0]["starred"] is True
    assert payload["articles"][0]["note"] == "중요 메모"

    target_date = "2025-02-02"
    imported = client.post(f"/api/exports/{target_date}.json", json=payload)
    assert imported.status_code == 200
    assert imported.json()["data"]["articlesImported"] == 1

    reexported = client.get(f"/api/exports/{target_date}.json").json()["data"]
    assert reexported["articles"][0]["note"] == "중요 메모"
    assert reexported["articles"][0]["starred"] is True
    assert reexported["articles"][0]["included"] == payload["articles"][0]["included"]


def test_json_schema_v7_round_trip_preserves_kesco_press_origin():
    source_date = "2025-02-18"
    article_id = _setup_briefing_with_article(source_date)
    connection = get_connection()
    try:
        with connection:
            press_release_repo.upsert_release(
                connection,
                {
                    "id": "kesco:991825",
                    "bbsSeq": "991825",
                    "title": "복지 사각지대도 전기안전 지킨다",
                    "publishedAt": "2025-02-18T00:00:00Z",
                    "bodyText": "정식 백업으로 보존할 공사 보도자료 원문입니다.",
                    "url": "https://www.kesco.or.kr/bbs/pr/selectBbs.do?bbs_code=MKB00002&bbs_seq=991825",
                    "fetchedAt": "2025-02-18T00:05:00Z",
                },
            )
            press_release_repo.upsert_origin(
                connection,
                article_id,
                {
                    "originType": "kesco_based",
                    "pressReleaseId": "kesco:991825",
                    "confidence": 0.81,
                    "reasons": {"titleSimilarity": 0.72},
                },
                "test-origin-v1",
            )
    finally:
        connection.close()

    payload = client.get(f"/api/exports/{source_date}.json").json()["data"]
    assert payload["schemaVersion"] == 12
    assert payload["articles"][0]["origin"]["pressRelease"]["bodyText"].startswith(
        "정식 백업"
    )

    target_date = "2025-02-19"
    imported = client.post(f"/api/exports/{target_date}.json", json=payload)
    assert imported.status_code == 200
    restored = client.get(
        "/api/articles", params={"report_date": target_date}
    ).json()["data"]["articles"][0]
    assert restored["origin"]["effectiveType"] == "kesco_based"
    assert restored["origin"]["pressReleaseId"] == "kesco:991825"
    assert restored["origin"]["pressRelease"]["bodyText"].startswith("정식 백업")

    connection = get_connection()
    try:
        with connection:
            connection.execute(
                """
                UPDATE article_origin_assessments
                SET final_origin_type = 'independent', final_press_release_id = NULL,
                    manual_override = 1
                WHERE article_id = ?
                """,
                (article_id,),
            )
    finally:
        connection.close()

    manual_payload = client.get(f"/api/exports/{source_date}.json").json()["data"]
    manual_date = "2025-02-20"
    imported = client.post(f"/api/exports/{manual_date}.json", json=manual_payload)
    assert imported.status_code == 200
    manual_restored = client.get(
        "/api/articles", params={"report_date": manual_date}
    ).json()["data"]["articles"][0]
    assert manual_restored["origin"]["effectiveType"] == "independent"
    assert manual_restored["origin"]["pressReleaseId"] is None
    assert manual_restored["origin"]["manualOverride"] is True


def test_json_import_conflicts_without_replace_mode():
    report_date = "2025-02-03"
    _setup_briefing_with_article(report_date)
    exported = client.get(f"/api/exports/{report_date}.json").json()["data"]

    conflict = client.post(f"/api/exports/{report_date}.json", json=exported)
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IMPORT_CONFLICT"

    replaced = client.post(f"/api/exports/{report_date}.json?mode=replace", json=exported)
    assert replaced.status_code == 200


def test_json_import_rejects_unsupported_schema_version():
    response = client.post(
        "/api/exports/2025-02-04.json",
        json={"schemaVersion": 999, "briefing": {}, "articles": []},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "IMPORT_SCHEMA_UNSUPPORTED"


def test_json_schema_v6_round_trip_preserves_incident_and_accepts_v5():
    report_date = "2025-02-13"
    client.put(f"/api/briefings/{report_date}", json={"expectedRevision": 0, "patch": {}})
    client.post(
        "/api/articles",
        json={
            "reportDate": report_date,
            "title": "공장 화재 1명 사망, 원인 조사 중",
            "source": "테스트일보",
            "url": "https://example.com/exports/incident-fire",
            "description": "재산피해 규모는 아직 확인되지 않았다.",
            "category": "major_fire_breaking",
        },
    )

    payload = client.get(f"/api/exports/{report_date}.json").json()["data"]
    assert payload["schemaVersion"] == 12
    assert payload["articles"][0]["incident"]["incident_type"] == "fire"
    assert payload["articles"][0]["incident"]["cause_status"] == "unknown"
    assert payload["articles"][0]["incident"]["cause_certainty"] == "under_investigation"
    assert payload["articles"][0]["incident"]["cause_domain"] == "undetermined"
    assert payload["articles"][0]["incident"]["property_damage_krw"] is None
    payload["articles"][0]["matchedQueryIds"] = ["major_fire_breaking", "strategy_trends"]

    target_date = "2025-02-14"
    imported = client.post(f"/api/exports/{target_date}.json", json=payload)
    assert imported.status_code == 200
    restored = client.get(f"/api/exports/{target_date}.json").json()["data"]
    assert restored["articles"][0]["incident"] == payload["articles"][0]["incident"]
    assert restored["articles"][0]["category"] == "major_fire_breaking"
    assert restored["articles"][0]["matchedQueryIds"] == ["major_fire_breaking", "strategy_trends"]

    legacy_payload = {**payload, "schemaVersion": 5, "articles": []}
    legacy_import = client.post("/api/exports/2025-02-15.json", json=legacy_payload)
    assert legacy_import.status_code == 200


def test_json_round_trip_preserves_issue_editor_and_membership_override():
    report_date = "2025-02-09"
    first = _setup_briefing_with_article(report_date)
    second_response = client.post(
        "/api/articles",
        json={
            "reportDate": report_date,
            "title": "수출입 테스트 기사 후속 보도",
            "source": "다른일보",
            "url": "https://example.com/exports/issue-second",
            "description": "설명",
            "category": "safety",
        },
    )
    second = second_response.json()["data"]["id"]
    run = client.post(
        "/api/cluster-runs", json={"reportDate": report_date, "asOf": "2025-02-09T12:00:00Z"}
    ).json()["data"]
    client.post(f"/api/cluster-runs/{run['id']}/apply")
    issues = client.get("/api/issues", params={"report_date": report_date}).json()["data"]["issues"]
    issue = next(item for item in issues if first in item["articleIds"])
    client.patch(
        f"/api/issues/{issue['id']}",
        json={
            "editorTitle": "백업할 담당자 제목",
            "editorPriority": "required",
            "articleId": second,
            "membershipAction": "add",
        },
    )
    payload = client.get(f"/api/exports/{report_date}.json").json()["data"]
    assert payload["schemaVersion"] == 12

    target_date = "2025-02-10"
    imported = client.post(f"/api/exports/{target_date}.json", json=payload)
    assert imported.status_code == 200
    assert imported.json()["data"]["issuesImported"] >= 1
    restored = client.get("/api/issues", params={"report_date": target_date}).json()["data"]["issues"]
    restored_issue = next(item for item in restored if item["effectiveTitle"] == "백업할 담당자 제목")
    assert restored_issue["effectivePriority"] == "required"
    assert len(restored_issue["articleIds"]) == 2
    assert restored_issue["membershipOverrides"][0]["action"] == "add"


def test_json_round_trip_preserves_direct_coverage_manual_override():
    source_date = "2025-03-21"
    client.put(
        f"/api/briefings/{source_date}",
        json={"expectedRevision": 0, "patch": {}},
    )
    article_id = client.post(
        "/api/articles",
        json={
            "reportDate": source_date,
            "title": "한국전기안전공사 해외사업 성과 소개",
            "source": "전기신문",
            "url": "https://example.com/exports/direct-coverage",
            "description": "공사 직접 보도 백업 테스트",
            "category": "kesco_direct",
        },
    ).json()["data"]["id"]
    run = client.post(
        "/api/cluster-runs",
        json={"reportDate": source_date, "asOf": "2025-03-21T12:00:00Z"},
    ).json()["data"]
    client.post(f"/api/cluster-runs/{run['id']}/apply")
    issue = client.get(
        "/api/issues", params={"report_date": source_date}
    ).json()["data"]["issues"][0]
    revision = client.get(f"/api/briefings/{source_date}").json()["data"]["revision"]
    overridden = client.patch(
        f"/api/briefings/{source_date}/issues/{issue['id']}",
        json={"expectedRevision": revision, "directCoverage": False},
    ).json()["data"]
    selected = client.patch(
        f"/api/briefings/{source_date}/articles/{article_id}",
        json={"expectedRevision": overridden["revision"], "selected": True},
    )
    assert selected.status_code == 200

    payload = client.get(f"/api/exports/{source_date}.json").json()["data"]
    assert payload["schemaVersion"] == 12
    assert payload["issues"][0]["editorDirectCoverage"] is False
    assert payload["issues"][0]["directCoverage"] is False

    target_date = "2025-03-22"
    imported = client.post(f"/api/exports/{target_date}.json", json=payload)
    assert imported.status_code == 200
    restored_issue = client.get(
        "/api/issues", params={"report_date": target_date}
    ).json()["data"]["issues"][0]
    assert restored_issue["editorDirectCoverage"] is False
    assert restored_issue["directCoverage"] is False
    restored_article = client.get(
        "/api/articles", params={"report_date": target_date}
    ).json()["data"]["articles"][0]
    assert restored_article["included"] is True


def test_json_round_trip_preserves_standalone_direct_coverage_override():
    source_date = "2025-03-23"
    client.put(
        f"/api/briefings/{source_date}",
        json={"expectedRevision": 0, "patch": {}},
    )
    article_id = client.post(
        "/api/articles",
        json={
            "reportDate": source_date,
            "title": "KESCO 단독 직접 보도",
            "source": "전기신문",
            "url": "https://example.com/exports/standalone-direct",
            "description": "그룹화 전 수동 해제 백업 테스트",
            "category": "kesco_direct",
        },
    ).json()["data"]["id"]
    revision = client.get(f"/api/briefings/{source_date}").json()["data"]["revision"]
    overridden = client.patch(
        f"/api/briefings/{source_date}/articles/{article_id}",
        json={"expectedRevision": revision, "directCoverage": False},
    ).json()["data"]
    selected = client.patch(
        f"/api/briefings/{source_date}/articles/{article_id}",
        json={"expectedRevision": overridden["revision"], "selected": True},
    )
    assert selected.status_code == 200

    payload = client.get(f"/api/exports/{source_date}.json").json()["data"]
    assert payload["articles"][0]["editorDirectCoverage"] is False
    assert payload["articles"][0]["directCoverage"] is False
    target_date = "2025-03-24"
    assert client.post(f"/api/exports/{target_date}.json", json=payload).status_code == 200
    restored = client.get(
        "/api/articles", params={"report_date": target_date}
    ).json()["data"]["articles"][0]
    assert restored["editorDirectCoverage"] is False
    assert restored["directCoverage"] is False
    assert restored["included"] is True


def test_json_schema_v5_round_trip_preserves_ai_run_and_article_body(monkeypatch):
    import json

    from backend.app.main import app

    analysis = {
        "managementMessage": {"text": "메시지", "articleIds": ["A01"]},
        "situationSummary": {"text": "요약", "articleIds": ["A01"]},
        "keyIssues": [],
        "decisionPoints": [],
        "actionItems": [],
        "riskOutlook": {"text": "전망", "articleIds": ["A01"], "isInference": True},
        "limitations": [],
        "confidence": "medium",
    }

    class FakeOllama:
        calls = 0

        def generate(self, *, model, prompt, format_schema=None, cancel_token=None):  # noqa: ARG002
            self.calls += 1
            if self.calls == 1:
                return json.dumps(
                    {
                        "items": [{
                            "section": "core",
                            "articleFact": "기사 내용이 확인됐다.",
                            "attributedClaim": "",
                            "kescoInterpretation": "공사 관점에서 살펴볼 사안이다.",
                            "managementRecommendation": "관련 현황을 확인할 필요가 있다.",
                                "articleIds": ["A01"],
                                "certainty": "confirmed",
                                "evidenceQuotes": [{"articleId": "A01", "fact": "기사 내용"}],
                                "electricalCauseStatus": "not_applicable",
                                "kescoJurisdiction": "DIRECT",
                                "jurisdictionReason": "공사 관련 기사",
                                "excludedElements": [],
                                "actionLevel": "internal_review",
                                "ownerType": "KESCO",
                        }],
                        "limitations": [],
                        "confidence": "medium",
                    },
                    ensure_ascii=False,
                )
            return json.dumps(analysis, ensure_ascii=False)

    report_date = "2025-02-11"
    _setup_briefing_with_article(report_date)
    full_text = "정식 JSON 백업으로 보존할 기사 전문입니다. " * 20
    monkeypatch.setattr(
        "backend.app.api.analysis.article_body.fetch_article_body",
        lambda url: BodyFetchResult(full_text, "full_text"),
    )
    app.state.ollama_client = FakeOllama()
    briefing = client.get(f"/api/briefings/{report_date}").json()["data"]
    analyzed = client.post(
        f"/api/briefings/{report_date}/analyze",
        json={"expectedRevision": briefing["revision"], "model": "gemma-test"},
    )
    assert analyzed.status_code == 200
    payload = client.get(f"/api/exports/{report_date}.json").json()["data"]
    assert payload["schemaVersion"] == 12
    assert payload["aiRuns"][0]["evidence"]
    assert payload["articles"][0]["bodyText"] == full_text

    connection = get_connection()
    try:
        with connection:
            connection.execute(
                "UPDATE articles SET body_text = '', body_status = 'missing', body_error = '' "
                "WHERE id = ?",
                (payload["articles"][0]["id"],),
            )
    finally:
        connection.close()

    target_date = "2025-02-12"
    imported = client.post(f"/api/exports/{target_date}.json", json=payload)
    assert imported.status_code == 200
    assert imported.json()["data"]["aiRunsImported"] == 1
    restored = client.get(f"/api/exports/{target_date}.json").json()["data"]
    assert restored["aiRuns"][0]["response"]["analysis"] == payload["aiRuns"][0]["response"]["analysis"]
    assert restored["articles"][0]["bodyText"] == full_text
    assert restored["articles"][0]["bodyStatus"] == "full_text"


def test_csv_export_escapes_formula_prefixed_cells():
    report_date = "2025-02-05"
    client.put(f"/api/briefings/{report_date}", json={"expectedRevision": 0, "patch": {}})
    client.post(
        "/api/articles",
        json={
            "reportDate": report_date,
            "title": "=1+1 위험 수식 제목",
            "source": "@테스트출판사",
            "url": "https://example.com/exports/formula",
            "description": "설명",
            "category": "safety",
        },
    )
    response = client.get(f"/api/exports/{report_date}.csv")
    assert response.status_code == 200
    text = response.text
    assert "\"'=1+1 위험 수식 제목\"" in text
    assert "\"'@테스트출판사\"" in text


def test_csv_export_import_round_trip_preserves_risk_and_selection():
    report_date = "2025-02-06"
    _setup_briefing_with_article(report_date)
    csv_text = client.get(f"/api/exports/{report_date}.csv").text

    target_date = "2025-02-07"
    client.put(f"/api/briefings/{target_date}", json={"expectedRevision": 0, "patch": {}})
    imported = client.post(f"/api/exports/{target_date}.csv", json={"csv": csv_text})
    assert imported.status_code == 200
    assert imported.json()["data"]["articlesImported"] == 1

    listed = client.get("/api/articles", params={"report_date": target_date}).json()["data"]["articles"]
    assert len(listed) == 1
    assert listed[0]["starred"] is True
    assert listed[0]["note"] == "중요 메모"


def test_csv_round_trip_preserves_incident_and_exports_unknowns_as_blanks():
    report_date = "2025-02-16"
    client.put(f"/api/briefings/{report_date}", json={"expectedRevision": 0, "patch": {}})
    client.post(
        "/api/articles",
        json={
            "reportDate": report_date,
            "title": "창고 화재, 피해 규모 파악 중",
            "source": "테스트일보",
            "url": "https://example.com/exports/csv-incident",
            "description": "소방당국이 큰불을 진화하고 있다.",
            "category": "major_fire_breaking",
        },
    )
    csv_text = client.get(f"/api/exports/{report_date}.csv").text
    rows = list(csv.DictReader(io.StringIO(csv_text.lstrip("﻿"))))
    assert rows[0]["분류"] == "중대화재·원인 미상 속보"
    assert rows[0]["주분류"] == "중대화재·원인 미상 속보"
    assert rows[0]["사고유형"] == "fire"
    assert rows[0]["원인상태"] == "unknown"
    assert rows[0]["원인확정수준"] == "unknown"
    assert rows[0]["원인분야"] == "undetermined"
    assert rows[0]["사망"] == ""
    assert rows[0]["재산피해"] == ""
    rows[0]["검색일치항목"] = "major_fire_breaking|strategy_trends"
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=rows[0].keys(), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    csv_text = "﻿" + buffer.getvalue()

    target_date = "2025-02-17"
    client.put(f"/api/briefings/{target_date}", json={"expectedRevision": 0, "patch": {}})
    imported = client.post(f"/api/exports/{target_date}.csv", json={"csv": csv_text})
    assert imported.status_code == 200
    restored = client.get("/api/articles", params={"report_date": target_date}).json()["data"]["articles"]
    assert restored[0]["incident"]["incident_type"] == "fire"
    assert restored[0]["incident"]["deaths"] is None
    assert restored[0]["category"] == "major_fire_breaking"
    assert restored[0]["matchedQueryIds"] == ["major_fire_breaking", "strategy_trends"]
    restored_csv = client.get(f"/api/exports/{target_date}.csv").text
    restored_row = next(csv.DictReader(io.StringIO(restored_csv.lstrip("﻿"))))
    assert restored_row["검색일치항목"] == "major_fire_breaking|strategy_trends"


def test_csv_import_requires_existing_briefing():
    response = client.post(
        "/api/exports/2099-02-08.csv",
        json={"csv": "﻿\"브리핑선정\"\r\n"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "BRIEFING_NOT_FOUND"
