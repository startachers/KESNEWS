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
    assert "textarea" not in preview.text

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


def test_final_snapshot_preserves_ai_evidence_article_link():
    report_date = "2026-09-03"
    article_id = _create_selected_article(report_date)
    analysis = {
        "managementMessage": {"text": "안전점검 보도를 확인해야 한다.", "articleIds": ["A01"]},
        "situationSummary": {"text": "직접 보도가 확인됐다.", "articleIds": ["A01"]},
        "keyIssues": [{"title": "안전점검", "urgency": "review", "summary": "직접 보도", "managementImpact": "후속 확인", "articleIds": ["A01"]}],
        "decisionPoints": [{"text": "확산 추이를 확인한다.", "articleIds": ["A01"]}],
        "actionItems": [{"priority": "review", "action": "사실관계를 점검한다.", "articleIds": ["A01"]}],
        "riskOutlook": {"text": "후속 보도가 이어질 수 있다.", "articleIds": ["A01"], "isInference": True},
        "limitations": [],
        "confidence": "medium",
    }

    class FakeOllama:
        def generate(self, *, model, prompt, format_schema=None, cancel_token=None):  # noqa: ARG002
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
    assert f'href="#article-{article_id}"' in report
    assert "AI 핵심 이슈" in report
    assert "AI 확인·지시 제안" in report
    assert "위험 전망(추론)" in report


def test_schema_v4_backup_round_trip_preserves_final_version():
    source_date = "2026-09-04"
    _create_selected_article(source_date)
    briefing = client.get(f"/api/briefings/{source_date}").json()["data"]
    client.post(
        f"/api/briefings/{source_date}/finalize",
        json={"expectedRevision": briefing["revision"]},
    )
    payload = client.get(f"/api/exports/{source_date}.json").json()["data"]
    assert payload["schemaVersion"] == 8
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
