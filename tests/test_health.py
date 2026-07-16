from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.api import operations as operations_api

client = TestClient(app)


def test_health_returns_flat_ok_shape():
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["service"] == "kesco-media-briefing"
    assert body["instanceId"]
    assert isinstance(body["models"], list)
    assert isinstance(body["defaultModel"], str)
    assert body["error"] is None or isinstance(body["error"], str)
    assert body["dbConnected"] is True
    assert body["dbIntegrity"] is True


def test_index_html_is_served_at_root():
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert 'id="restartServerBtn"' in response.text
    assert response.text.index('id="restartServerBtn"') < response.text.index('id="refreshBtn"')
    assert "js/app.js?v=20260716-15" in response.text


def test_restart_requires_confirmation_header(monkeypatch):
    scheduled = []
    monkeypatch.setattr(operations_api, "schedule_server_restart", scheduled.append)

    response = client.post("/api/operations/restart")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "SYSTEM_RESTART_FORBIDDEN"
    assert scheduled == []


def test_restart_schedules_helper_after_confirmed_request(monkeypatch):
    scheduled = []
    monkeypatch.setattr(operations_api, "schedule_server_restart", scheduled.append)

    response = client.post(
        "/api/operations/restart", headers={"X-KESCO-Restart": "confirmed"}
    )

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "restarting"
    assert scheduled == [response.json()["data"]["processId"]]
