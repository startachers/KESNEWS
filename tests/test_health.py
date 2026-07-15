from fastapi.testclient import TestClient

from backend.app.main import app

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
