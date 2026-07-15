from fastapi.testclient import TestClient

from backend.app.services.collection import collector as collector_module
from backend.app.main import app

client = TestClient(app)


def _yonhap_result(**overrides):
    item = {
        "id": "raw-yonhap-1",
        "title": "한국전기안전공사 국정감사서 지적",
        "source": "연합뉴스",
        "url": "https://www.yna.co.kr/view/AKR2026071500001",
        "pubDate": "2026-07-15T09:00:00Z",
        "description": "국정감사에서 안전관리 실태가 지적됐다.",
        "provider": "연합뉴스 RSS",
    }
    item.update(overrides)
    return {"items": [item], "provider": "연합뉴스 RSS"}


def _google_result(**overrides):
    item = {
        "id": "raw-google-1",
        "title": "전기화재 예방 캠페인 실시",
        "source": "조선일보",
        "url": "https://www.chosun.com/national/2026/07/15/example/",
        "pubDate": "2026-07-15T08:00:00Z",
        "description": "전기화재 예방을 위한 캠페인이 실시됐다.",
        "provider": "Google 뉴스 RSS",
    }
    item.update(overrides)
    return {"items": [item], "provider": "Google 뉴스 RSS"}


def _base_payload(**overrides):
    payload = {
        "reportDate": "2026-07-15",
        "lookbackHours": 48,
        "maxRecordsPerQuery": 50,
        "collectionLimit": 200,
        "enableYonhap": True,
        "queries": [{"id": "direct", "label": "기관 직접", "query": "(\"한국전기안전공사\")"}],
        "coreKeywords": ["한국전기안전공사"],
        "riskKeywords": ["국정감사", "화재"],
        "positiveKeywords": [],
        "excludeKeywords": ["채용공고"],
        "endpoint": "",
        "existingArticles": [],
    }
    payload.update(overrides)
    return payload


def test_collections_merges_providers_and_returns_success(monkeypatch):
    monkeypatch.setattr(collector_module, "fetch_yonhap_rss", lambda *a, **k: _yonhap_result())
    monkeypatch.setattr(collector_module, "fetch_google_rss", lambda *a, **k: _google_result()["items"])

    response = client.post("/api/collections", json=_base_payload())
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["status"] == "success"
    titles = {article["title"] for article in data["articles"]}
    assert "한국전기안전공사 국정감사서 지적" in titles
    assert "전기화재 예방 캠페인 실시" in titles
    assert data["rawCollectedCount"] == 2


def test_collections_preserves_manual_and_existing_selection_state(monkeypatch):
    monkeypatch.setattr(collector_module, "fetch_yonhap_rss", lambda *a, **k: _yonhap_result())
    monkeypatch.setattr(collector_module, "fetch_google_rss", lambda *a, **k: [])

    existing = [
        {
            "id": "existing-yonhap",
            "title": "한국전기안전공사 국정감사서 지적",
            "source": "연합뉴스",
            "url": "https://www.yna.co.kr/view/AKR2026071500001",
            "pubDate": "2026-07-15T09:00:00Z",
            "description": "국정감사에서 안전관리 실태가 지적됐다.",
            "risk": "watch",
            "included": True,
            "starred": True,
            "note": "담당자 메모",
            "manual": False,
        },
        {
            "id": "manual-1",
            "title": "직접 등록한 사내 소식",
            "source": "사내소식",
            "url": "https://intra.example.com/news/1",
            "pubDate": "2026-07-15T07:00:00Z",
            "description": "수동으로 등록한 기사.",
            "risk": "routine",
            "included": True,
            "starred": False,
            "note": "",
            "manual": True,
        },
    ]

    response = client.post("/api/collections", json=_base_payload(existingArticles=existing))
    assert response.status_code == 200
    data = response.json()["data"]
    matched = next(a for a in data["articles"] if a["url"] == "https://www.yna.co.kr/view/AKR2026071500001")
    assert matched["included"] is True
    assert matched["starred"] is True
    assert matched["note"] == "담당자 메모"
    assert any(a["id"] == "manual-1" for a in data["articles"])


def test_collections_returns_failed_status_when_all_providers_fail(monkeypatch):
    def _raise(*args, **kwargs):
        raise RuntimeError("연결 실패")

    monkeypatch.setattr(collector_module, "fetch_yonhap_rss", _raise)
    monkeypatch.setattr(collector_module, "fetch_google_rss", _raise)
    monkeypatch.setattr(collector_module, "fetch_gdelt_combined", _raise)

    response = client.post("/api/collections", json=_base_payload())
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["status"] == "failed"
    assert body["data"]["articles"] == []
    assert body["data"]["errors"]


def test_collections_falls_back_to_gdelt_when_rss_providers_fail(monkeypatch):
    def _raise(*args, **kwargs):
        raise RuntimeError("연결 실패")

    gdelt_item = {
        "id": "raw-gdelt-1",
        "title": "한국전기안전공사 관련 GDELT 기사",
        "source": "example.com",
        "url": "https://example.com/gdelt/1",
        "pubDate": "2026-07-15T09:30:00Z",
        "description": "GDELT로 수집된 기사.",
        "provider": "GDELT",
    }
    monkeypatch.setattr(collector_module, "fetch_yonhap_rss", _raise)
    monkeypatch.setattr(collector_module, "fetch_google_rss", _raise)
    monkeypatch.setattr(collector_module, "fetch_gdelt_combined", lambda *a, **k: [gdelt_item])

    response = client.post("/api/collections", json=_base_payload())
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "success"
    assert data["provider"] == "GDELT"
    assert any("RSS 보조 전환" in w for w in data["warnings"])


def test_collections_rejects_request_without_any_source():
    response = client.post(
        "/api/collections", json=_base_payload(enableYonhap=False, queries=[])
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "COLLECTION_NO_SOURCE"
