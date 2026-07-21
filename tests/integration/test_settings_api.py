from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app.api import collections as collections_api
from backend.app.main import app
from backend.app.repositories import settings_repository as settings_repo
from backend.app.repositories.database import get_connection

client = TestClient(app)


def _clear_override() -> None:
    connection = get_connection()
    try:
        with connection:
            settings_repo.delete_override(connection)
    finally:
        connection.close()


@pytest.fixture(autouse=True)
def clean_settings_override():
    _clear_override()
    yield
    _clear_override()


def _defaults() -> dict:
    response = client.get("/api/settings")
    assert response.status_code == 200
    return response.json()["data"]


def test_settings_get_put_and_reset_round_trip():
    defaults = _defaults()
    assert len(defaults["queries"]) == 22
    assert defaults["lookback"] == 24

    changed = {
        **defaults,
        "collectionLimit": 321,
        "coreKeywords": ["한국전기안전공사", "사용자 키워드"],
        "queries": [
            {**query, "enabled": query["id"] != "ai_trend"}
            for query in defaults["queries"]
        ],
    }
    saved = client.put("/api/settings", json=changed)
    assert saved.status_code == 200
    assert saved.json()["meta"]["hasOverride"] is True
    assert saved.json()["meta"]["updatedAt"]

    loaded = client.get("/api/settings").json()
    assert loaded["data"]["collectionLimit"] == 321
    assert loaded["data"]["coreKeywords"][-1] == "사용자 키워드"
    assert loaded["data"]["queries"][-1]["enabled"] is False

    reset = client.post("/api/settings/reset")
    assert reset.status_code == 200
    assert reset.json()["meta"]["hasOverride"] is False
    assert reset.json()["data"] == defaults


def test_settings_validation_rejects_invalid_values_without_overwriting():
    defaults = _defaults()
    invalid = {**defaults, "coreKeywords": [], "maxRecords": 19}

    response = client.put("/api/settings", json=invalid)

    assert response.status_code == 422
    assert client.get("/api/settings").json()["data"] == defaults


def test_collection_uses_server_settings_and_ignores_legacy_body(monkeypatch):
    defaults = _defaults()
    server_query = {
        "id": "server_only",
        "label": "서버 검색식",
        "enabled": True,
        "query": "한국전기안전공사 서버",
        "naverQueries": ["전기안전공사"],
    }
    configured = {
        **defaults,
        "enableYonhap": False,
        "enableOpmPress": False,
        "enableMePress": False,
        "queries": [server_query],
        "coreKeywords": ["서버 핵심어"],
    }
    assert client.put("/api/settings", json=configured).status_code == 200
    captured = {}

    async def fake_collection(payload):
        captured.update(payload)
        return {"status": "success"}

    monkeypatch.setattr(collections_api, "run_collection", fake_collection)
    response = client.post(
        "/api/collections",
        json={
            "report_date": "2026-07-21",
            "lookback_hours": 72,
            "queries": [{"id": "body_value", "query": "무시할 검색식"}],
            "coreKeywords": ["무시할 키워드"],
            "enableYonhap": True,
        },
    )

    assert response.status_code == 200
    assert captured["reportDate"] == "2026-07-21"
    assert captured["lookbackHours"] == 24
    assert captured["queries"] == [server_query]
    assert captured["coreKeywords"] == ["서버 핵심어"]
    assert captured["enableYonhap"] is False


def test_collection_rejects_server_configuration_without_any_source():
    defaults = _defaults()
    disabled = {
        **defaults,
        "enableYonhap": False,
        "enableOpmPress": False,
        "enableMePress": False,
        "queries": [{**query, "enabled": False} for query in defaults["queries"]],
    }
    assert client.put("/api/settings", json=disabled).status_code == 200

    response = client.post("/api/collections", json={"report_date": "2026-07-21"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "COLLECTION_NO_SOURCE"
