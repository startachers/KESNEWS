from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from backend.app.api import weather as weather_api
from backend.app.core.clock import today_seoul
from backend.app.main import app
from backend.app.repositories import weather_repository as weather_repo
from backend.app.repositories.database import get_connection

client = TestClient(app)


def _fake_weather_result(report_date: str):
    return {
        "regionConfigVersion": "test-regions-v1",
        "riskRuleVersion": "test-rules-v1",
        "sourceStatus": {
            "alerts": {"status": "success", "issuedAt": f"{report_date}T06:00:00+09:00", "error": None},
            "shortForecast": {"status": "success", "issuedAt": f"{report_date}T05:00:00+09:00", "error": None},
            "midForecast": {"status": "success", "issuedAt": f"{report_date}T06:00:00+09:00", "error": None},
        },
        "days": [
            {
                "date": report_date,
                "weatherText": "비",
                "temperature": {"min": 23, "max": 35, "isNationalRange": True},
                "maxPrecipitationProbability": 80,
                "maxHourlyPrecipitation": {"text": "30~50mm", "min": 30, "max": 50, "unit": "mm/h"},
                "dailyPrecipitation": {"text": "120~200mm", "min": 120, "max": 200, "unit": "mm/day"},
                "maxWindSpeed": 6.2,
                "riskLevel": "watch",
                "affectedRegionCount": 2,
                "source": "kma_short",
            }
        ],
        "alerts": [{"title": "호우주의보", "issuedAt": f"{report_date}T06:00:00+09:00", "regionIds": ["capital", "chungcheong"]}],
        "signals": [
            {
                "signalKey": "heavy-rain-test",
                "hazard": "heavy_rain",
                "level": "watch",
                "startsAt": f"{report_date}T06:00:00+09:00",
                "endsAt": None,
                "regionIds": ["capital", "chungcheong"],
                "electricalRisks": ["누전·감전 위험"],
                "recommendedChecks": ["침수 취약시설 사전점검"],
                "evidence": [{"provider": "kma_alert", "officialIssuedAt": f"{report_date}T06:00:00+09:00"}],
                "confidence": "high",
                "ruleId": "test-rule",
            }
        ],
        "providers": [
            {
                "provider": "alerts",
                "status": "success",
                "issuedAt": f"{report_date}T06:00:00+09:00",
                "items": [{"title": "호우주의보"}],
                "observations": [],
                "error": None,
            },
            {
                "provider": "shortForecast",
                "status": "success",
                "issuedAt": f"{report_date}T05:00:00+09:00",
                "items": [{}],
                "observations": [],
                "error": None,
            },
            {
                "provider": "midForecast",
                "status": "success",
                "issuedAt": f"{report_date}T06:00:00+09:00",
                "items": [{}],
                "observations": [],
                "error": None,
            },
        ],
        "overallLevel": "watch",
        "periodFrom": report_date,
        "periodTo": report_date,
        "issuedAt": f"{report_date}T06:00:00+09:00",
        "inputSignature": "test-weather-signature",
    }


def test_weather_refresh_review_and_final_snapshot(monkeypatch):
    report_date = "2099-12-31"
    monkeypatch.setattr(weather_api, "today_seoul", lambda: report_date)
    monkeypatch.setenv("KMA_SERVICE_KEY", "test-key")
    monkeypatch.setattr(
        weather_api,
        "collect",
        lambda service_key, requested_date: _fake_weather_result(requested_date),
    )
    created = client.put(
        f"/api/briefings/{report_date}",
        json={"expectedRevision": 0, "patch": {"preparedBy": "홍보실"}},
    )
    assert created.status_code == 200

    refreshed = client.post(
        "/api/weather/refresh", json={"reportDate": report_date}
    )
    assert refreshed.status_code == 200
    weather = refreshed.json()["data"]
    context = weather["latestContext"]
    assert context["overallLevel"] == "watch"
    assert context["riskSignals"][0]["hazard"] == "heavy_rain"

    revision = created.json()["data"]["revision"]
    attached = client.put(
        f"/api/briefings/{report_date}/weather",
        json={
            "expectedRevision": revision,
            "contextId": context["id"],
            "includeInReport": True,
            "reviewStatus": "reviewed",
            "selectedSignals": [
                {
                    "id": context["riskSignals"][0]["id"],
                    "selected": True,
                    "editorLevel": "critical",
                    "editorNote": "침수 취약시설 우선 확인",
                }
            ],
            "editorNote": "특보와 취약시설 점검사항 확인",
        },
    )
    assert attached.status_code == 200
    attached_data = attached.json()["data"]
    assert attached_data["weather"]["attached"]["reviewStatus"] == "reviewed"
    assert attached_data["weather"]["attached"]["signals"][0]["editorLevel"] == "critical"
    assert attached_data["weather"]["attached"]["signals"][0]["editorNote"] == "침수 취약시설 우선 확인"

    preview = client.get(f"/preview/{report_date}")
    assert preview.status_code == 200
    assert "기상 기반 선제대응" in preview.text
    assert "(폭우)" in preview.text
    assert "(폭염)" not in preview.text
    assert "최대 시간당 50mm · 일 최대 200mm / 수도권·충청" in preview.text
    assert "우려: 누전·감전 위험" in preview.text
    assert preview.text.count('<article class="weather-forecast') == 1
    assert "강수확률" not in preview.text
    assert "전국 위험도" not in preview.text
    assert "긴급" not in preview.text
    assert "영향 권역" not in preview.text
    assert "우선 확인" not in preview.text
    assert 'class="weather-day' not in preview.text
    assert 'class="weather-forecast' in preview.text
    assert preview.text.index("참고 동향") < preview.text.index("기상 기반 선제대응")

    finalized = client.post(
        f"/api/briefings/{report_date}/finalize",
        json={"expectedRevision": attached_data["briefing"]["revision"]},
    )
    assert finalized.status_code == 200
    snapshot = client.get(
        f"/api/briefings/{report_date}/versions/1"
    ).json()["data"]["snapshot"]
    assert snapshot["weather"]["context"]["inputSignature"] == "test-weather-signature"
    assert snapshot["weather"]["context"]["riskSignals"][0]["autoLevel"] == "watch"
    assert snapshot["weather"]["context"]["riskSignals"][0]["level"] == "critical"
    assert snapshot["weather"]["context"]["riskSignals"][0]["editorNote"] == "침수 취약시설 우선 확인"


def test_weather_not_configured_is_explicit(monkeypatch):
    monkeypatch.delenv("KMA_SERVICE_KEY", raising=False)
    report_date = today_seoul()
    response = client.post("/api/weather/refresh", json={"reportDate": report_date})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "WEATHER_NOT_CONFIGURED"


def test_weather_run_detail_and_not_found(monkeypatch):
    report_date = "2026-07-17"
    monkeypatch.setattr(weather_api, "today_seoul", lambda: report_date)
    monkeypatch.setenv("KMA_SERVICE_KEY", "test-key")
    monkeypatch.setattr(
        weather_api,
        "collect",
        lambda service_key, requested_date: _fake_weather_result(requested_date),
    )

    refreshed = client.post(
        "/api/weather/refresh", json={"reportDate": report_date}
    ).json()["data"]
    run_id = refreshed["latestRun"]["id"]

    response = client.get(f"/api/weather/runs/{run_id}")
    assert response.status_code == 200
    assert response.json()["data"]["id"] == run_id
    assert {item["provider"] for item in response.json()["data"]["providers"]} == {
        "alerts",
        "shortForecast",
        "midForecast",
    }

    missing = client.get("/api/weather/runs/missing-run")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "WEATHER_RUN_NOT_FOUND"


def test_stale_running_collection_does_not_block_refresh(monkeypatch):
    report_date = "2099-12-30"
    monkeypatch.setattr(weather_api, "today_seoul", lambda: report_date)
    monkeypatch.setenv("KMA_SERVICE_KEY", "test-key")
    monkeypatch.setattr(
        weather_api,
        "collect",
        lambda service_key, requested_date: _fake_weather_result(requested_date),
    )
    connection = get_connection()
    try:
        with connection:
            stale = weather_repo.create_run(connection, report_date)
            old_started_at = (
                datetime.now(timezone.utc) - timedelta(hours=1)
            ).isoformat().replace("+00:00", "Z")
            connection.execute(
                "UPDATE weather_collection_runs SET started_at = ? WHERE id = ?",
                (old_started_at, stale["id"]),
            )
    finally:
        connection.close()

    response = client.post("/api/weather/refresh", json={"reportDate": report_date})

    assert response.status_code == 200
    connection = get_connection()
    try:
        expired = connection.execute(
            "SELECT status, finished_at, error_count FROM weather_collection_runs WHERE id = ?",
            (stale["id"],),
        ).fetchone()
    finally:
        connection.close()
    assert expired["status"] == "failed"
    assert expired["finished_at"]
    assert expired["error_count"] == 1


def test_weather_json_round_trip_preserves_review_and_shifts_report_days(monkeypatch):
    source_date = "2099-12-29"
    target_date = "2100-01-02"
    monkeypatch.setattr(weather_api, "today_seoul", lambda: source_date)
    monkeypatch.setenv("KMA_SERVICE_KEY", "test-key")
    monkeypatch.setattr(
        weather_api,
        "collect",
        lambda service_key, requested_date: _fake_weather_result(requested_date),
    )
    created = client.put(
        f"/api/briefings/{source_date}",
        json={"expectedRevision": 0, "patch": {"preparedBy": "홍보실"}},
    ).json()["data"]
    context = client.post(
        "/api/weather/refresh", json={"reportDate": source_date}
    ).json()["data"]["latestContext"]
    attached = client.put(
        f"/api/briefings/{source_date}/weather",
        json={
            "expectedRevision": created["revision"],
            "contextId": context["id"],
            "includeInReport": True,
            "reviewStatus": "reviewed",
            "selectedSignals": [
                {"id": context["riskSignals"][0]["id"], "selected": True}
            ],
            "editorNote": "JSON 왕복 검증",
        },
    )
    assert attached.status_code == 200

    payload = client.get(f"/api/exports/{source_date}.json").json()["data"]
    imported = client.post(f"/api/exports/{target_date}.json", json=payload)
    assert imported.status_code == 200
    restored = client.get(f"/api/exports/{target_date}.json").json()["data"]["weather"]

    assert restored["attachment"]["reviewStatus"] == "reviewed"
    assert restored["attachment"]["includeInReport"] is True
    assert restored["attachment"]["editorNote"] == "JSON 왕복 검증"
    assert restored["context"]["reportDate"] == target_date
    assert restored["context"]["days"][0]["date"] == target_date
    assert len(restored["context"]["riskSignals"]) == 1
    assert restored["attachment"]["signals"][0]["selected"] is True


def test_finalize_rejects_unreviewed_weather(monkeypatch):
    report_date = "2099-12-26"
    monkeypatch.setattr(weather_api, "today_seoul", lambda: report_date)
    monkeypatch.setenv("KMA_SERVICE_KEY", "test-key")
    monkeypatch.setattr(
        weather_api,
        "collect",
        lambda service_key, requested_date: _fake_weather_result(requested_date),
    )
    created = client.put(
        f"/api/briefings/{report_date}",
        json={"expectedRevision": 0, "patch": {}},
    ).json()["data"]
    context = client.post(
        "/api/weather/refresh", json={"reportDate": report_date}
    ).json()["data"]["latestContext"]
    attached = client.put(
        f"/api/briefings/{report_date}/weather",
        json={
            "expectedRevision": created["revision"],
            "contextId": context["id"],
            "includeInReport": True,
            "reviewStatus": "pending",
            "selectedSignals": [],
            "editorNote": "",
        },
    ).json()["data"]["briefing"]

    finalized = client.post(
        f"/api/briefings/{report_date}/finalize",
        json={"expectedRevision": attached["revision"]},
    )

    assert finalized.status_code == 409
    assert finalized.json()["error"]["code"] == "WEATHER_REVIEW_REQUIRED"
