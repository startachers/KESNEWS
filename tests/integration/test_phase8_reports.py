import json
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)


def _create_selected_article(report_date: str) -> str:
    created = client.put(
        f"/api/briefings/{report_date}",
        json={"expectedRevision": 0, "patch": {"preparedBy": "홍보실", "actionNote": "1차 지시"}},
    )
    assert created.status_code == 200
    article = client.post(
        "/api/articles",
        json={
            "reportDate": report_date,
            "title": f"{report_date} 한국전기안전공사 안전점검 보도",
            "source": "테스트일보",
            "url": f"https://example.com/report/{report_date}",
            "description": "전기안전 취약시설 점검을 확대했다.",
            "category": "direct",
        },
    )
    assert article.status_code == 200
    return article.json()["data"]["id"]


def test_finalize_reopen_and_second_version_are_immutable():
    report_date = "2026-09-01"
    article_id = _create_selected_article(report_date)
    before = client.get(f"/api/briefings/{report_date}").json()["data"]

    first = client.post(
        f"/api/briefings/{report_date}/finalize",
        json={"expectedRevision": before["revision"]},
    )
    assert first.status_code == 200
    first_data = first.json()["data"]
    assert first_data["version"] == 1
    assert first_data["briefing"]["status"] == "final"
    assert Path(first_data["reportHtmlPath"]).is_file()

    locked = client.put(
        f"/api/briefings/{report_date}",
        json={"expectedRevision": first_data["briefing"]["revision"], "patch": {"actionNote": "변경"}},
    )
    assert locked.status_code == 409
    assert locked.json()["error"]["code"] == "BRIEFING_FINALIZED"
    manual = client.post(
        "/api/articles",
        json={"reportDate": report_date, "title": "잠금 뒤 기사", "source": "테스트"},
    )
    assert manual.status_code == 409

    reopened = client.post(
        f"/api/briefings/{report_date}/reopen",
        json={"expectedRevision": first_data["briefing"]["revision"]},
    )
    assert reopened.status_code == 200
    reopened_data = reopened.json()["data"]
    assert reopened_data["status"] == "draft"

    changed = client.put(
        f"/api/briefings/{report_date}",
        json={"expectedRevision": reopened_data["revision"], "patch": {"actionNote": "2차 지시"}},
    ).json()["data"]
    second = client.post(
        f"/api/briefings/{report_date}/finalize",
        json={"expectedRevision": changed["revision"]},
    )
    assert second.status_code == 200
    assert second.json()["data"]["version"] == 2

    versions = client.get(f"/api/briefings/{report_date}/versions").json()["data"]["versions"]
    assert [item["version"] for item in versions] == [2, 1]
    v1 = client.get(f"/api/briefings/{report_date}/versions/1").json()["data"]["snapshot"]
    v2 = client.get(f"/api/briefings/{report_date}/versions/2").json()["data"]["snapshot"]
    assert v1["briefing"]["actionNote"] == "1차 지시"
    assert v2["briefing"]["actionNote"] == "2차 지시"
    assert v1["articles"][0]["id"] == article_id


def test_preview_and_report_routes_are_read_only_and_versioned():
    report_date = "2026-09-02"
    _create_selected_article(report_date)
    preview = client.get(f"/preview/{report_date}")
    assert preview.status_code == 200
    assert "작업본 미리보기" in preview.text
    assert "AI 분석 이후 선정 기사·메모·이슈 연결이 변경된 상태" not in preview.text
    assert "textarea" not in preview.text
    assert preview.text.count('<section class="report-page') == 2
    assert preview.text.count(" data-fit-page>") == 2
    assert "padding:12mm 7mm" in preview.text
    assert "--report-scale:.93" in preview.text
    assert "--copy-size:14px" in preview.text
    assert ".page-inner{width:100%;transform:scale(var(--report-scale));transform-origin:top center}" in preview.text
    assert "-webkit-print-color-adjust:exact;print-color-adjust:exact" in preview.text
    assert "@media screen and (max-width:760px)" in preview.text
    assert "const fitAll" not in preview.text
    assert "zoom:.68" not in preview.text
    assert "grid-template-columns:minmax(0,1fr) auto" in preview.text
    assert '<div class="article-main"><div class="article-title-row"><h3>' in preview.text
    assert '</p></div><p class="desc">' in preview.text
    assert ".article h3{min-width:0;margin:0;overflow:hidden;font-size:16px" in preview.text
    assert ".article .desc{min-width:0;margin:2px 0 0;overflow:hidden;color:#42505a;font-size:14.5px" in preview.text
    assert "제목과 핵심 요약을 각각 한 줄로 정리했습니다." in preview.text
    assert '<div class="kpis">' not in preview.text
    assert '<span class="number">' not in preview.text

    assert client.get(f"/report/{report_date}").status_code == 404
    briefing = client.get(f"/api/briefings/{report_date}").json()["data"]
    client.post(
        f"/api/briefings/{report_date}/finalize",
        json={"expectedRevision": briefing["revision"]},
    )
    latest = client.get(f"/report/{report_date}")
    specified = client.get(f"/report/{report_date}?version=1")
    assert latest.status_code == specified.status_code == 200
    assert "최종본 v1" in latest.text
    assert "onclick=\"window.print()\"" in latest.text
    missing = client.get(f"/api/briefings/{report_date}/versions/99")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "BRIEFING_VERSION_NOT_FOUND"


def test_preview_rebuild_excludes_article_deselected_after_previous_preview():
    report_date = "2026-09-20"
    article_id = _create_selected_article(report_date)
    article_anchor = f'id="article-{article_id}"'

    first_preview = client.get(f"/preview/{report_date}")
    assert first_preview.status_code == 200
    assert article_anchor in first_preview.text

    briefing = client.get(f"/api/briefings/{report_date}").json()["data"]
    deselected = client.patch(
        f"/api/briefings/{report_date}/articles/{article_id}",
        json={"expectedRevision": briefing["revision"], "selected": False},
    )
    assert deselected.status_code == 200

    refreshed_preview = client.get(f"/preview/{report_date}")
    assert refreshed_preview.status_code == 200
    assert article_anchor not in refreshed_preview.text


def test_final_snapshot_preserves_ai_evidence_article_link():
    report_date = "2026-09-03"
    article_id = _create_selected_article(report_date)
    analysis = {
        "managementMessage": {"text": "안전점검 보도를 확인해야 한다.", "articleIds": ["A01"]},
        "situationSummary": {"text": "직접 보도가 확인됐다.", "articleIds": ["A01"]},
        "keyIssues": [{"title": "안전점검", "urgency": "review", "summary": "직접 보도", "managementImpact": "후속 확인", "articleIds": ["A01"], "evidenceQuotes": [{"articleId": "A01", "fact": "안전점검 보도"}], "certainty": "confirmed", "electricalCauseStatus": "not_applicable", "kescoJurisdiction": "DIRECT", "jurisdictionReason": "공사 점검 업무", "excludedElements": [], "recommendation": "사실관계를 점검한다.", "actionLevel": "internal_review"}],
        "decisionPoints": [{"text": "확산 추이를 확인한다.", "articleIds": ["A01"]}],
        "actionItems": [{"priority": "review", "action": "사실관계를 점검한다.", "articleIds": ["A01"], "kescoJurisdiction": "DIRECT", "actionLevel": "internal_review", "evidence": "안전점검 보도", "uncertainty": "confirmed", "ownerType": "KESCO"}],
        "riskOutlook": {"text": "후속 보도가 이어질 수 있다.", "articleIds": ["A01"], "isInference": True},
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
                            "articleFact": "안전점검 보도가 확인됐다.",
                            "attributedClaim": "",
                            "kescoInterpretation": "공사 관점에서 살펴볼 사안이다.",
                            "managementRecommendation": "사실관계를 점검할 필요가 있다.",
                            "articleIds": ["A01"],
                            "certainty": "confirmed",
                            "evidenceQuotes": [{"articleId": "A01", "fact": "안전점검 보도"}],
                            "electricalCauseStatus": "not_applicable",
                            "kescoJurisdiction": "DIRECT",
                            "jurisdictionReason": "공사 점검 업무",
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

    app.state.ollama_client = FakeOllama()
    briefing = client.get(f"/api/briefings/{report_date}").json()["data"]
    analyzed = client.post(
        f"/api/briefings/{report_date}/analyze",
        json={"expectedRevision": briefing["revision"], "model": "gemma-test"},
    )
    assert analyzed.status_code == 200
    revision = analyzed.json()["data"]["briefingRevision"]
    client.post(
        f"/api/briefings/{report_date}/finalize", json={"expectedRevision": revision}
    )
    snapshot = client.get(
        f"/api/briefings/{report_date}/versions/1"
    ).json()["data"]["snapshot"]
    assert snapshot["evidence"]["A01"]["articleId"] == article_id
    assert snapshot["evidence"]["A01"]["article"]["title"]
    report = client.get(f"/report/{report_date}").text
    assert f'id="article-{article_id}"' in report
    assert "① 오늘 한줄" in report
    assert "② 언론 동향 분석" in report
    assert "③ 경영 참고사항" in report
    assert "직접 보도가 확인됐다." in report
    assert "후속 확인" not in report
    assert "후속 보도가 이어질 수 있다." not in report
    assert "의사결정 포인트" not in report
    assert "확산 추이를 확인한다." not in report
    assert "실행 항목" not in report
    assert "사실관계를 점검한다." in report
    assert "관련 기사" in report
    assert "분석 근거" not in report
    assert "근거 기사 링크" not in report
    assert "관련 기사 모음" not in report
    assert 'class="evidence-list"' not in report
    assert "CEO 참고·지시사항" not in report
    assert "CEO 보고 편집본" not in report
    assert ">A01</" not in report


def test_schema_v4_backup_round_trip_preserves_final_version():
    source_date = "2026-09-04"
    _create_selected_article(source_date)
    briefing = client.get(f"/api/briefings/{source_date}").json()["data"]
    client.post(
        f"/api/briefings/{source_date}/finalize",
        json={"expectedRevision": briefing["revision"]},
    )
    payload = client.get(f"/api/exports/{source_date}.json").json()["data"]
    assert payload["schemaVersion"] == 12
    assert len(payload["briefingVersions"]) == 1

    target_date = "2026-09-05"
    imported = client.post(f"/api/exports/{target_date}.json", json=payload)
    assert imported.status_code == 200
    assert imported.json()["data"]["versionsImported"] == 1
    restored = client.get(f"/api/briefings/{target_date}/versions/1")
    assert restored.status_code == 200
    restored_snapshot = restored.json()["data"]["snapshot"]
    assert restored_snapshot["reportDate"] == target_date
    assert client.get(f"/report/{target_date}").status_code == 200


def test_final_export_scopes_and_immutable_import_conflict():
    report_date = "2026-09-06"
    _create_selected_article(report_date)
    briefing = client.get(f"/api/briefings/{report_date}").json()["data"]
    client.post(
        f"/api/briefings/{report_date}/finalize",
        json={"expectedRevision": briefing["revision"]},
    )

    latest = client.get(
        f"/api/exports/{report_date}.json", params={"scope": "latest-final"}
    )
    specified_csv = client.get(
        f"/api/exports/{report_date}.csv", params={"scope": "version:1"}
    )
    assert latest.status_code == 200
    assert latest.json()["data"]["briefingVersions"][0]["version"] == 1
    assert specified_csv.status_code == 200
    assert "안전점검 보도" in specified_csv.text
    assert client.get(
        f"/api/exports/{report_date}.json", params={"scope": "version:99"}
    ).status_code == 404

    payload = client.get(f"/api/exports/{report_date}.json").json()["data"]
    payload["briefingVersions"][0]["snapshot"]["briefing"]["actionNote"] = "변조"
    conflict = client.post(
        f"/api/exports/{report_date}.json?mode=replace", json=payload
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["details"]["reason"] == "immutable_final_snapshot_differs"
    preserved = client.get(f"/api/briefings/{report_date}/versions/1").json()["data"]
    assert preserved["snapshot"]["briefing"]["actionNote"] == "1차 지시"
