from fastapi.testclient import TestClient

from backend.app.main import app

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
    assert payload["schemaVersion"] == 1
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


def test_csv_import_requires_existing_briefing():
    response = client.post(
        "/api/exports/2099-02-08.csv",
        json={"csv": "﻿\"브리핑선정\"\r\n"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "BRIEFING_NOT_FOUND"
