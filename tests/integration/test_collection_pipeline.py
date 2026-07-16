from fastapi.testclient import TestClient

from backend.app.repositories.database import get_connection
from backend.app.services.collection import collector as collector_module
from backend.app.main import app

client = TestClient(app)


def _yonhap_result(url, pub_date, **overrides):
    item = {
        "id": "raw-yonhap-1",
        "title": "한국전기안전공사 국정감사서 지적",
        "source": "연합뉴스",
        "url": url,
        "pubDate": pub_date,
        "description": "국정감사에서 전기안전 관리 실태가 지적됐다.",
        "provider": "연합뉴스 RSS",
    }
    item.update(overrides)
    return {"items": [item], "provider": "연합뉴스 RSS"}


def _google_result(url, pub_date, **overrides):
    item = {
        "id": "raw-google-1",
        "title": "전기화재 예방 캠페인 실시",
        "source": "조선일보",
        "url": url,
        "pubDate": pub_date,
        "description": "전기화재 예방을 위한 캠페인이 실시됐다.",
        "provider": "Google 뉴스 RSS",
        "sourceUrl": url,
    }
    item.update(overrides)
    return {"items": [item], "provider": "Google 뉴스 RSS"}


def _base_payload(**overrides):
    payload = {
        "reportDate": "2025-01-15",
        "lookbackHours": 48,
        "maxRecordsPerQuery": 50,
        "collectionLimit": 200,
        "enableYonhap": True,
        "enableOpmPress": False,
        "enableMePress": False,
        "queries": [{"id": "direct", "label": "기관 직접", "query": "(\"한국전기안전공사\")"}],
        "coreKeywords": ["한국전기안전공사"],
        "riskKeywords": ["국정감사", "화재"],
        "positiveKeywords": [],
        "excludeKeywords": ["채용공고"],
        "endpoint": "",
    }
    payload.update(overrides)
    return payload


def _articles(report_date: str, **params):
    response = client.get("/api/articles", params={"report_date": report_date, **params})
    assert response.status_code == 200
    return response.json()


def test_collections_merges_providers_and_returns_success(monkeypatch):
    report_date = "2025-01-15"
    yonhap_url = "https://www.yna.co.kr/view/AKR2026071500001-merge"
    google_url = "https://www.chosun.com/national/2026/07/15/merge/"
    monkeypatch.setattr(
        collector_module, "fetch_yonhap_rss", lambda *a, **k: _yonhap_result(yonhap_url, f"{report_date}T09:00:00Z", title="병합 테스트 국정감사 기사")
    )
    monkeypatch.setattr(
        collector_module,
        "fetch_google_rss",
        lambda *a, **k: _google_result(google_url, f"{report_date}T08:00:00Z", title="병합 테스트 전기화재 캠페인")["items"],
    )

    response = client.post("/api/collections", json=_base_payload(reportDate=report_date))
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["status"] == "success"
    assert data["rawCollectedCount"] == 2
    assert data["uniqueCount"] == 2
    assert data["source_filter_stats"] == {
        "raw_results": 2,
        "official_sources": 0,
        "trusted_media": 2,
        "rejected_untrusted_media": 0,
        "unknown_publisher": 0,
    }
    assert "articles" not in data

    listed = _articles(report_date)
    urls = {article["url"] for article in listed["data"]["articles"]}
    assert yonhap_url in urls
    assert google_url in urls
    google_article = next(a for a in listed["data"]["articles"] if a["url"] == google_url)
    assert google_article["publisherId"] == "chosun"
    assert google_article["publisherAllowed"] is True

    latest = client.get("/api/collections/latest", params={"report_date": report_date})
    assert latest.status_code == 200
    assert latest.json()["data"]["source_filter_stats"] == data["source_filter_stats"]


def test_repeat_collection_merges_same_article_without_duplicating(monkeypatch):
    report_date = "2025-01-16"
    yonhap_url = "https://www.yna.co.kr/view/AKR2026071600001-repeat"
    monkeypatch.setattr(
        collector_module, "fetch_yonhap_rss", lambda *a, **k: _yonhap_result(yonhap_url, f"{report_date}T09:00:00Z", title="반복 테스트 국정감사 기사")
    )
    monkeypatch.setattr(collector_module, "fetch_google_rss", lambda *a, **k: [])

    first = client.post("/api/collections", json=_base_payload(reportDate=report_date)).json()["data"]
    assert first["newCount"] == 1
    second = client.post("/api/collections", json=_base_payload(reportDate=report_date)).json()["data"]
    assert second["matchedCount"] == 1
    assert second["newCount"] == 0

    listed = _articles(report_date)["data"]["articles"]
    matching = [a for a in listed if a["url"] == yonhap_url]
    assert len(matching) == 1


def test_source_id_match_survives_url_change_between_runs(monkeypatch):
    """기관 어댑터가 부여한 source_id가 같으면, 사이트 개편으로 URL이 바뀌어도 같은 기사로 병합한다."""
    report_date = "2025-01-20"

    def _gov_item(url, title):
        return {
            "id": "raw-gov-1",
            "title": title,
            "source": "정책브리핑",
            "url": url,
            "pubDate": f"{report_date}T09:00:00Z",
            "description": "한국전기안전공사 국정감사 관련 정부부처 보도자료 본문입니다.",
            "provider": "정책브리핑 API",
            "sourceId": "policy-briefing:123456",
        }

    monkeypatch.setattr(collector_module, "fetch_yonhap_rss", lambda *a, **k: {"items": [], "provider": "연합뉴스 RSS"})
    monkeypatch.setattr(
        collector_module,
        "fetch_google_rss",
        lambda *a, **k: [_gov_item("https://www.korea.kr/briefing/pressReleaseView.do?newsId=1", "전기안전 대책 발표")],
    )

    first = client.post("/api/collections", json=_base_payload(reportDate=report_date)).json()["data"]
    assert first["newCount"] == 1

    monkeypatch.setattr(
        collector_module,
        "fetch_google_rss",
        lambda *a, **k: [_gov_item("https://www.korea.kr/briefing/pressReleaseView.do?newsId=1&page=2", "전기안전 대책 발표(수정)")],
    )
    second = client.post("/api/collections", json=_base_payload(reportDate=report_date)).json()["data"]
    assert second["matchedCount"] == 1
    assert second["newCount"] == 0

    listed = _articles(report_date)["data"]["articles"]
    matching = [a for a in listed if a["title"].startswith("전기안전 대책 발표")]
    assert len(matching) == 1


def test_direct_government_sources_default_on_and_bypass_relevance_filter(monkeypatch):
    report_date = "2025-01-26"
    gov_item = {
        "id": "raw-opm-1",
        "sourceId": "opm:123456",
        "title": "정례 브리핑 자료",
        "source": "국무조정실 보도자료",
        "url": "https://www.opm.go.kr/opm/news/press-release.do?mode=view&articleNo=123456",
        "pubDate": f"{report_date}T09:00:00Z",
        "description": "담당 부서 안내",
        "provider": "국무조정실 보도자료",
    }
    excluded_item = {
        **gov_item,
        "id": "raw-opm-2",
        "sourceId": "opm:123457",
        "title": "채용공고 안내",
        "url": "https://www.opm.go.kr/opm/news/press-release.do?mode=view&articleNo=123457",
    }
    monkeypatch.setattr(
        collector_module,
        "fetch_opm_press",
        lambda *a, **k: {
            "items": [gov_item, excluded_item],
            "provider": "국무조정실 보도자료",
        },
    )
    monkeypatch.setattr(
        collector_module,
        "fetch_me_press",
        lambda *a, **k: {"items": [], "provider": "기후에너지환경부 보도자료"},
    )

    # enableOpmPress/enableMePress를 보내지 않는 구버전 프런트 요청도 기본 활성화한다.
    payload = _base_payload(reportDate=report_date, enableYonhap=False, queries=[])
    payload.pop("enableOpmPress")
    payload.pop("enableMePress")
    response = client.post("/api/collections", json=payload)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["rawCollectedCount"] == 2
    assert data["uniqueCount"] == 1

    listed = _articles(report_date)["data"]["articles"]
    article = next(item for item in listed if item["url"] == gov_item["url"])
    assert article["assessment"]["effectivePriority"] == "review"
    assert article["assessment"]["autoReasons"]["relevanceRank"] == 99
    assert "official_government_source" in article["assessment"]["autoReasons"]["appliedFloors"]
    assert all(item["url"] != excluded_item["url"] for item in listed)


def test_legacy_unclassified_article_is_hidden_unless_editor_state_exists(monkeypatch):
    report_date = "2025-01-23"
    url = "https://www.yna.co.kr/view/AKR2026072300001-legacy"
    monkeypatch.setattr(
        collector_module,
        "fetch_yonhap_rss",
        lambda *a, **k: _yonhap_result(
            url,
            f"{report_date}T09:00:00Z",
            title="전환 회귀 한국전기안전공사 국정감사 기사",
        ),
    )
    monkeypatch.setattr(collector_module, "fetch_google_rss", lambda *a, **k: [])

    client.post("/api/collections", json=_base_payload(reportDate=report_date))
    article = next(a for a in _articles(report_date)["data"]["articles"] if a["url"] == url)

    connection = get_connection()
    try:
        with connection:
            connection.execute(
                "UPDATE articles SET publisher_id = NULL, publisher_allowed = NULL WHERE id = ?",
                (article["id"],),
            )
    finally:
        connection.close()

    assert _articles(report_date)["data"]["articles"] == []

    briefing = client.put(
        f"/api/briefings/{report_date}", json={"expectedRevision": 0, "patch": {}}
    ).json()["data"]
    patch = client.patch(
        f"/api/briefings/{report_date}/articles/{article['id']}",
        json={
            "expectedRevision": briefing["revision"],
            "selected": True,
            "starred": True,
            "note": "기존 담당자 메모 보존",
        },
    )
    assert patch.status_code == 200
    preserved = _articles(report_date)["data"]["articles"]
    assert len(preserved) == 1
    assert preserved[0]["included"] is True
    assert preserved[0]["starred"] is True
    assert preserved[0]["note"] == "기존 담당자 메모 보존"


def test_manual_selection_state_survives_recollection(monkeypatch):
    report_date = "2025-01-17"
    yonhap_url = "https://www.yna.co.kr/view/AKR2026071700001-manual"
    monkeypatch.setattr(
        collector_module, "fetch_yonhap_rss", lambda *a, **k: _yonhap_result(yonhap_url, f"{report_date}T09:00:00Z", title="수동 보존 테스트 국정감사 기사")
    )
    monkeypatch.setattr(collector_module, "fetch_google_rss", lambda *a, **k: [])

    client.put(f"/api/briefings/{report_date}", json={"expectedRevision": 0, "patch": {}})
    client.post("/api/collections", json=_base_payload(reportDate=report_date))

    listed = _articles(report_date)["data"]["articles"]
    article_id = next(a["id"] for a in listed if a["url"] == yonhap_url)

    briefing = client.get(f"/api/briefings/{report_date}").json()["data"]
    client.patch(
        f"/api/briefings/{report_date}/articles/{article_id}",
        json={"expectedRevision": briefing["revision"], "selected": True, "starred": True, "note": "담당자 메모"},
    )

    # 재수집 — LEG-001/P3-002 해소: 수집은 selected/starred/note를 건드리지 않는다.
    client.post("/api/collections", json=_base_payload(reportDate=report_date))

    reloaded = _articles(report_date)["data"]["articles"]
    reloaded_article = next(a for a in reloaded if a["id"] == article_id)
    assert reloaded_article["included"] is True
    assert reloaded_article["starred"] is True
    assert reloaded_article["note"] == "담당자 메모"


def test_partial_failure_preserves_previously_collected_articles(monkeypatch):
    report_date = "2025-01-18"
    yonhap_url = "https://www.yna.co.kr/view/AKR2026071800001-partial"
    google_url = "https://www.chosun.com/national/2026/07/18/partial/"
    monkeypatch.setattr(
        collector_module, "fetch_yonhap_rss", lambda *a, **k: _yonhap_result(yonhap_url, f"{report_date}T09:00:00Z", title="부분실패 테스트 국정감사 기사")
    )
    monkeypatch.setattr(
        collector_module,
        "fetch_google_rss",
        lambda *a, **k: _google_result(google_url, f"{report_date}T08:00:00Z", title="부분실패 테스트 전기화재 캠페인")["items"],
    )
    first = client.post("/api/collections", json=_base_payload(reportDate=report_date)).json()["data"]
    assert first["status"] == "success"

    def _raise(*args, **kwargs):
        raise RuntimeError("검색식 연결 실패")

    monkeypatch.setattr(collector_module, "fetch_google_rss", _raise)
    second = client.post("/api/collections", json=_base_payload(reportDate=report_date)).json()["data"]
    assert second["status"] == "partial"

    listed = _articles(report_date)
    items = listed["data"]["articles"]
    yonhap_article = next(a for a in items if a["url"] == yonhap_url)
    google_article = next(a for a in items if a["url"] == google_url)
    assert yonhap_article["stale"] is False
    assert google_article["stale"] is True
    assert google_article["staleReason"] == "provider_failed"
    assert listed["meta"]["failedProviders"]


def test_collections_returns_failed_status_when_all_providers_fail(monkeypatch):
    def _raise(*args, **kwargs):
        raise RuntimeError("연결 실패")

    monkeypatch.setattr(collector_module, "fetch_yonhap_rss", _raise)
    monkeypatch.setattr(collector_module, "fetch_google_rss", _raise)
    monkeypatch.setattr(collector_module, "fetch_gdelt_combined", _raise)

    response = client.post("/api/collections", json=_base_payload(reportDate="2025-01-19"))
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["status"] == "failed"
    assert body["data"]["errors"]


def test_collections_falls_back_to_gdelt_when_rss_providers_fail(monkeypatch):
    report_date = "2025-01-20"

    def _raise(*args, **kwargs):
        raise RuntimeError("연결 실패")

    gdelt_item = {
        "id": "raw-gdelt-1",
        "title": "한국전기안전공사 관련 GDELT 기사",
        "source": "조선일보",
        "url": "https://www.chosun.com/gdelt/1",
        "pubDate": f"{report_date}T09:30:00Z",
        "description": "GDELT로 수집된 기사.",
        "provider": "GDELT",
    }
    monkeypatch.setattr(collector_module, "fetch_yonhap_rss", _raise)
    monkeypatch.setattr(collector_module, "fetch_google_rss", _raise)
    monkeypatch.setattr(collector_module, "fetch_gdelt_combined", lambda *a, **k: [gdelt_item])

    response = client.post("/api/collections", json=_base_payload(reportDate=report_date))
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "success"
    assert data["provider"] == "GDELT"
    assert any("RSS 보조 전환" in w for w in data["warnings"])

    listed = _articles(report_date)["data"]["articles"]
    assert any(a["url"] == "https://www.chosun.com/gdelt/1" for a in listed)


def test_untrusted_and_google_without_source_url_are_rejected_with_stats(monkeypatch):
    report_date = "2025-01-21"
    monkeypatch.setattr(
        collector_module,
        "fetch_yonhap_rss",
        lambda *a, **k: {"items": [], "provider": "연합뉴스 RSS"},
    )
    items = [
        _google_result(
            "https://outside.example/article/1",
            f"{report_date}T09:00:00Z",
            title="한국전기안전공사 관련 허용목록 밖 기사",
        )["items"][0],
        _google_result(
            "https://news.google.com/rss/articles/no-source",
            f"{report_date}T08:00:00Z",
            title="한국전기안전공사 관련 출처 미상 기사",
            sourceUrl="",
        )["items"][0],
    ]
    monkeypatch.setattr(collector_module, "fetch_google_rss", lambda *a, **k: items)

    data = client.post("/api/collections", json=_base_payload(reportDate=report_date)).json()["data"]
    assert data["uniqueCount"] == 0
    assert data["source_filter_stats"]["rejected_untrusted_media"] == 2
    assert data["source_filter_stats"]["unknown_publisher"] == 1
    assert _articles(report_date)["data"]["articles"] == []


def test_official_google_source_bypasses_media_allowlist(monkeypatch):
    report_date = "2025-01-22"
    monkeypatch.setattr(
        collector_module,
        "fetch_yonhap_rss",
        lambda *a, **k: {"items": [], "provider": "연합뉴스 RSS"},
    )
    official = _google_result(
        "https://news.google.com/rss/articles/official",
        f"{report_date}T09:00:00Z",
        title="대통령실 전력망 안전 대책 발표",
        source="대통령실",
        sourceUrl="https://www.president.go.kr/newsroom/briefing",
    )["items"][0]
    monkeypatch.setattr(collector_module, "fetch_google_rss", lambda *a, **k: [official])

    data = client.post("/api/collections", json=_base_payload(reportDate=report_date)).json()["data"]
    assert data["uniqueCount"] == 1
    assert data["source_filter_stats"]["official_sources"] == 1
    article = _articles(report_date)["data"]["articles"][0]
    assert article["publisherId"] == "official:president.go.kr"


def test_collections_rejects_request_without_any_source():
    response = client.post(
        "/api/collections", json=_base_payload(enableYonhap=False, queries=[])
    )
    assert response.status_code == 400
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "COLLECTION_NO_SOURCE"
