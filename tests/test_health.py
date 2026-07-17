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
    assert "js/restart-guard.js?v=20260716-1" in response.text
    assert "js/app.js?v=20260717-3" in response.text
    assert 'id="searchProgress"' in response.text
    assert 'role="progressbar"' in response.text
    assert "css/app.css?v=20260717-14" in response.text
    assert 'id="autoSelectBtn" type="button" aria-busy="false"' in response.text

    app_script = client.get("/js/app.js")
    assert 'dialogs.js?v=20260716-19' in app_script.text
    assert 'articles.js?v=20260716-15' in app_script.text
    assert 'collection.js?v=20260716-19' in app_script.text
    assert 'notifications.js?v=20260716-1' in app_script.text
    assert 'dataset.restartHandler = "module"' in app_script.text

    restart_guard = client.get("/js/restart-guard.js")
    assert restart_guard.status_code == 200
    assert 'button.dataset.restartHandler === "module"' in restart_guard.text
    assert '"X-KESCO-Restart": "confirmed"' in restart_guard.text
    assert 'cache: "no-store"' in restart_guard.text

    assert '<option value="collection">관련기사 수집순</option>' in response.text

    dialogs_script = client.get("/js/ui/dialogs.js")
    assert 'import { setStatus, showToast } from "./notifications.js?v=20260716-1";' in dialogs_script.text
    assert 'articles.js?v=20260716-15' in dialogs_script.text

    renderers_script = client.get("/js/ui/renderers.js")
    assert 'articles.js?v=20260716-15' in renderers_script.text

    auto_selection_script = client.get("/js/features/auto-selection.js")
    assert 'setAttribute("aria-busy", String(value))' in auto_selection_script.text

    stylesheet = client.get("/css/app.css")
    assert "button:disabled { cursor: not-allowed;" in stylesheet.text
    assert 'button[aria-busy="true"] { cursor: progress;' in stylesheet.text


def test_frontend_assets_disable_browser_cache():
    for path in ("/", "/js/app.js", "/css/app.css"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store, max-age=0"
        assert response.headers["pragma"] == "no-cache"


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
