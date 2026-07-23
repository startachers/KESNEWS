from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.app.core.clock import now_iso, today_seoul
from backend.app.repositories import article_repository as article_repo
from backend.app.repositories import press_release_repository as press_release_repo
from backend.app.repositories import run_repository as run_repo
from backend.app.repositories import settings_repository as settings_repo
from backend.app.repositories.database import get_connection
from backend.app.services.collection import collector as collector_module
from backend.app.services.collection.http import CollectionHttpError
from backend.app.services.settings import load_default_settings
from backend.app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolate_collection_settings_override():
    connection = get_connection()
    try:
        with connection:
            settings_repo.delete_override(connection)
    finally:
        connection.close()
    yield
    connection = get_connection()
    try:
        with connection:
            settings_repo.delete_override(connection)
    finally:
        connection.close()


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
    settings = load_default_settings().model_dump()
    settings.update(
        {
            "maxRecords": payload["maxRecordsPerQuery"],
            "collectionLimit": payload["collectionLimit"],
            "enableYonhap": payload["enableYonhap"],
            "enableOpmPress": payload["enableOpmPress"],
            "enableMePress": payload["enableMePress"],
            "queries": [{"enabled": True, **query} for query in payload["queries"]],
            "coreKeywords": payload["coreKeywords"],
            "riskKeywords": payload["riskKeywords"],
            "positiveKeywords": payload["positiveKeywords"],
            "excludeKeywords": payload["excludeKeywords"],
            "endpoint": payload["endpoint"],
        }
    )
    saved = client.put("/api/settings", json=settings)
    assert saved.status_code == 200, saved.text
    return {"report_date": payload["reportDate"], "lookback_hours": payload["lookbackHours"]}


def _articles(report_date: str, **params):
    response = client.get("/api/articles", params={"report_date": report_date, **params})
    assert response.status_code == 200
    return response.json()


def test_settings_rejects_per_query_limits_below_twenty():
    settings = load_default_settings().model_dump()
    global_limit = {**settings, "maxRecords": 19}
    query_override = load_default_settings().model_dump()
    query_override["queries"][0]["maxRecords"] = 19

    assert client.put("/api/settings", json=global_limit).status_code == 422
    assert client.put("/api/settings", json=query_override).status_code == 422


def test_article_list_hides_legacy_auto_candidate_outside_current_24_hours():
    report_date = today_seoul()
    now = datetime.now(timezone.utc)
    old_date = (now - timedelta(hours=25)).isoformat().replace("+00:00", "Z")
    recent_date = (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    connection = get_connection()
    try:
        with connection:
            run_id = run_repo.create_run(
                connection,
                report_date=report_date,
                started_at=now_iso(),
                lookback_hours=48,
            )
            provider_id = run_repo.add_provider_result(
                connection,
                run_id=run_id,
                provider="Google 뉴스 RSS",
                query_group_id="direct",
                status="success",
                started_at=now_iso(),
                finished_at=now_iso(),
                raw_count=2,
                accepted_count=2,
                duplicate_count=0,
                warning_message=None,
                error_code=None,
                error_message=None,
            )
            article_ids = []
            for suffix, published_at in (("old-window", old_date), ("recent-window", recent_date)):
                url = f"https://www.chosun.com/national/{suffix}/"
                article_id = article_repo.create_article(
                    connection,
                    url=url,
                    title=f"한국전기안전공사 {suffix} 기사",
                    source="조선일보",
                    published_at=published_at,
                    description="24시간 후보 범위 테스트",
                    category_hint="direct",
                    manual=False,
                    publisher_id="chosun",
                    publisher_allowed=True,
                )
                article_repo.insert_observation(
                    connection,
                    article_id=article_id,
                    collection_run_provider_id=provider_id,
                    provider="Google 뉴스 RSS",
                    provider_item_key=None,
                    query_group_id="direct",
                    raw_url=url,
                    raw_title=f"한국전기안전공사 {suffix} 기사",
                    raw_source="조선일보",
                    raw_published_at=published_at,
                    raw_description="24시간 후보 범위 테스트",
                    raw_payload_json=None,
                    dedup_method="new",
                    dedup_score=None,
                )
                article_ids.append(article_id)
            run_repo.finish_run(
                connection,
                run_id,
                status="success",
                finished_at=now_iso(),
                raw_count=2,
                accepted_count=2,
                unique_count=2,
                stale_reused_count=0,
                warning_count=0,
                error_count=0,
            )
    finally:
        connection.close()

    listed_ids = {item["id"] for item in _articles(report_date)["data"]["articles"]}
    assert article_ids[0] not in listed_ids
    assert article_ids[1] in listed_ids

    briefing_response = client.put(
        f"/api/briefings/{report_date}", json={"expectedRevision": 0, "patch": {}}
    )
    if briefing_response.status_code == 409:
        briefing_response = client.get(f"/api/briefings/{report_date}")
    assert briefing_response.status_code == 200
    briefing = briefing_response.json()["data"]
    empty_state = client.patch(
        f"/api/briefings/{report_date}/articles/{article_ids[0]}",
        json={"expectedRevision": briefing["revision"], "selected": False},
    )
    assert empty_state.status_code == 200
    assert article_ids[0] not in {
        item["id"] for item in _articles(report_date)["data"]["articles"]
    }

    patched = client.patch(
        f"/api/briefings/{report_date}/articles/{article_ids[0]}",
        json={
            "expectedRevision": empty_state.json()["data"]["revision"],
            "selected": True,
        },
    )
    assert patched.status_code == 200
    preserved_ids = {item["id"] for item in _articles(report_date)["data"]["articles"]}
    assert article_ids[0] in preserved_ids


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


def test_collection_reuses_content_key_when_legacy_canonical_url_is_missing(monkeypatch):
    report_date = "2025-01-31"
    url = "https://www.yna.co.kr/view/AKR202501310001-content-key"
    connection = get_connection()
    try:
        with connection:
            existing_id = article_repo.create_article(
                connection,
                url=url,
                title="과거 저장 제목",
                source="연합뉴스",
                published_at=f"{report_date}T09:00:00Z",
                description="기존 설명",
                category_hint="kesco_direct",
                manual=False,
                publisher_id="yonhap",
                publisher_allowed=True,
            )
            # 과거 import/정규화 데이터처럼 content_key는 URL 기반이지만 canonical_url이
            # 비어 있는 경계 사례를 재현한다.
            connection.execute(
                "UPDATE articles SET canonical_url = NULL WHERE id = ?", (existing_id,)
            )
    finally:
        connection.close()

    monkeypatch.setattr(
        collector_module,
        "fetch_yonhap_rss",
        lambda *a, **k: _yonhap_result(
            url,
            f"{report_date}T09:00:00Z",
            title="한국전기안전공사 국정감사 새 제목",
        ),
    )
    monkeypatch.setattr(collector_module, "fetch_google_rss", lambda *a, **k: [])

    response = client.post("/api/collections", json=_base_payload(reportDate=report_date))

    assert response.status_code == 200
    assert response.json()["data"]["matchedCount"] == 1
    connection = get_connection()
    try:
        matching = connection.execute(
            "SELECT id FROM articles WHERE content_key = (SELECT content_key FROM articles WHERE id = ?)",
            (existing_id,),
        ).fetchall()
        observation = connection.execute(
            "SELECT dedup_method FROM article_observations WHERE article_id = ? ORDER BY observed_at DESC LIMIT 1",
            (existing_id,),
        ).fetchone()
    finally:
        connection.close()
    assert [row["id"] for row in matching] == [existing_id]
    assert observation["dedup_method"] == "content_key"


def test_collection_links_media_article_to_kesco_press_release(monkeypatch):
    report_date = "2025-01-29"
    title = "복지 사각지대도 전기안전 지킨다 한국전기안전공사 협력"
    connection = get_connection()
    try:
        with connection:
            press_release_repo.upsert_release(
                connection,
                {
                    "id": "kesco:171545",
                    "bbsSeq": "171545",
                    "title": title,
                    "publishedAt": f"{report_date}T00:00:00Z",
                    "bodyText": "한국사회복지협의회와 협약해 취약계층 무료 전기안전 점검을 실시한다.",
                    "url": "https://www.kesco.or.kr/bbs/pr/selectBbs.do?bbs_code=MKB00002&bbs_seq=171545",
                    "fetchedAt": f"{report_date}T00:05:00Z",
                },
            )
    finally:
        connection.close()
    monkeypatch.setattr(
        collector_module,
        "fetch_yonhap_rss",
        lambda *a, **k: _yonhap_result(
            "https://www.yna.co.kr/view/AKR202501290001",
            f"{report_date}T03:00:00Z",
            title="복지 사각지대도 전기안전 지킨다…전기안전공사 협력",
            description="한국사회복지협의회와 협약해 취약계층 무료 전기안전 점검을 실시한다.",
        ),
    )
    monkeypatch.setattr(collector_module, "fetch_google_rss", lambda *a, **k: [])

    response = client.post(
        "/api/collections",
        json=_base_payload(reportDate=report_date),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["kescoPressReleaseCount"] >= 1
    assert data["kescoPressMatchedCount"] == 1
    article = _articles(report_date)["data"]["articles"][0]
    assert article["origin"]["effectiveType"] == "kesco_republication"
    assert article["origin"]["pressReleaseId"] == "kesco:171545"
    assert article["origin"]["pressRelease"]["title"] == title


def test_naver_and_google_same_article_create_two_observations(monkeypatch):
    report_date = "2025-01-27"
    url = "https://www.yna.co.kr/view/AKR202501270001"
    pub_date = f"{report_date}T09:00:00Z"
    monkeypatch.setenv("NAVER_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setattr(
        collector_module,
        "fetch_naver_news",
        lambda *a, **k: [
            {
                "title": "한국전기안전공사 안전대책 발표",
                "source": "yna.co.kr",
                "url": url,
                "originalLink": url,
                "naverUrl": "https://n.news.naver.com/article/001/1",
                "pubDate": pub_date,
                "description": "한국전기안전공사가 안전대책을 발표했다.",
                "provider": "네이버 뉴스 API",
            }
        ],
    )
    monkeypatch.setattr(
        collector_module,
        "fetch_google_rss",
        lambda *a, **k: _google_result(
            url,
            pub_date,
            title="한국전기안전공사 안전대책 발표",
            source="연합뉴스",
        )["items"],
    )

    payload = _base_payload(
        reportDate=report_date,
        enableYonhap=False,
        queries=[{
            "id": "direct",
            "label": "기관 직접",
            "query": '("한국전기안전공사")',
            "naverQueries": ["한국전기안전공사"],
        }],
    )
    data = client.post("/api/collections", json=payload).json()["data"]
    assert data["uniqueCount"] == 1
    assert data["duplicatesRemoved"] == 1
    assert data["naverStatus"] == "네이버 뉴스 API 연결됨"

    article_id = _articles(report_date)["data"]["articles"][0]["id"]
    connection = get_connection()
    try:
        observations = connection.execute(
            "SELECT provider, query_group_id FROM article_observations WHERE article_id = ?",
            (article_id,),
        ).fetchall()
    finally:
        connection.close()
    assert {(row["provider"], row["query_group_id"]) for row in observations} == {
        ("네이버 뉴스 API", "direct"),
        ("Google 뉴스 RSS", "direct"),
    }


def test_naver_and_yonhap_receive_pub_date_lookback_callback(monkeypatch):
    report_date = "2025-01-28"
    pub_date = f"{report_date}T09:00:00Z"
    monkeypatch.setenv("NAVER_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "test-client-secret")

    def fake_yonhap(within_lookback, collection_limit):
        assert within_lookback(pub_date) is True
        return _yonhap_result(
            "https://www.yna.co.kr/view/AKR202501280001-callback",
            pub_date,
        )

    def fake_naver(query, client_id, client_secret, within_lookback):
        assert query == "한국전기안전공사"
        assert (client_id, client_secret) == ("test-client-id", "test-client-secret")
        assert within_lookback(pub_date) is True
        return [
            {
                "title": "한국전기안전공사 전기화재 예방대책 발표",
                "source": "yna.co.kr",
                "url": "https://www.yna.co.kr/view/AKR202501280002-callback",
                "originalLink": "https://www.yna.co.kr/view/AKR202501280002-callback",
                "naverUrl": "https://n.news.naver.com/article/001/2",
                "pubDate": pub_date,
                "description": "한국전기안전공사가 전기화재 예방대책을 발표했다.",
                "provider": "네이버 뉴스 API",
            }
        ]

    monkeypatch.setattr(collector_module, "fetch_yonhap_rss", fake_yonhap)
    monkeypatch.setattr(collector_module, "fetch_naver_news", fake_naver)
    monkeypatch.setattr(collector_module, "fetch_google_rss", lambda *a, **k: [])

    payload = _base_payload(
        reportDate=report_date,
        queries=[{
            "id": "direct",
            "label": "기관 직접",
            "query": '("한국전기안전공사")',
            "naverQueries": ["한국전기안전공사"],
        }],
    )
    response = client.post("/api/collections", json=payload)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["naverStatus"] == "네이버 뉴스 API 연결됨"
    assert not any("'str' object has no attribute 'get'" in item for item in data.get("warnings", []))
    assert not any("'str' object has no attribute 'get'" in item for item in data.get("failures", []))


def test_naver_auth_failure_is_warning_and_never_exposes_credentials(monkeypatch):
    report_date = "2025-01-28"
    client_id = "sensitive-client-id"
    client_secret = "sensitive-client-secret"
    monkeypatch.setenv("NAVER_CLIENT_ID", client_id)
    monkeypatch.setenv("NAVER_CLIENT_SECRET", client_secret)
    monkeypatch.setattr(
        collector_module,
        "fetch_naver_news",
        lambda *a, **k: (_ for _ in ()).throw(
            CollectionHttpError("네이버 뉴스 API 응답 401", status=401)
        ),
    )
    monkeypatch.setattr(
        collector_module,
        "fetch_google_rss",
        lambda *a, **k: _google_result(
            "https://www.chosun.com/national/naver-fallback/",
            f"{report_date}T09:00:00Z",
            title="한국전기안전공사 네이버 장애 폴백",
        )["items"],
    )

    payload = _base_payload(
        reportDate=report_date,
        enableYonhap=False,
        queries=[{
            "id": "direct",
            "label": "기관 직접",
            "query": '("한국전기안전공사")',
            "naverQueries": ["한국전기안전공사"],
        }],
    )
    response = client.post("/api/collections", json=payload)
    serialized = response.text
    data = response.json()["data"]
    assert data["status"] == "success"
    assert data["uniqueCount"] == 1
    assert data["naverStatus"] == "네이버 뉴스 API 오류"
    assert any("응답 401" in warning for warning in data["warnings"])
    assert client_id not in serialized
    assert client_secret not in serialized
    client.put(f"/api/briefings/{report_date}", json={"expectedRevision": 0, "patch": {}})
    exported = client.get(f"/api/exports/{report_date}.json").text
    assert client_id not in exported
    assert client_secret not in exported


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
    expired_item = {
        **gov_item,
        "id": "raw-opm-3",
        "sourceId": "opm:123458",
        "title": "24시간이 지난 정례 브리핑",
        "url": "https://www.opm.go.kr/opm/news/press-release.do?mode=view&articleNo=123458",
        "pubDate": "2025-01-20T09:00:00Z",
    }
    previous_date_item = {
        **gov_item,
        "id": "raw-opm-4",
        "sourceId": "opm:123459",
        "title": "전일 등록 정례 브리핑",
        "url": "https://www.opm.go.kr/opm/news/press-release.do?mode=view&articleNo=123459",
        "pubDate": "2025-01-25T00:00:00Z",
    }
    monkeypatch.setattr(
        collector_module,
        "fetch_opm_press",
        lambda *a, **k: {
            "items": [gov_item, excluded_item, expired_item, previous_date_item],
            "provider": "국무조정실 보도자료",
        },
    )
    monkeypatch.setattr(
        collector_module,
        "fetch_me_press",
        lambda *a, **k: {"items": [], "provider": "기후에너지환경부 보도자료"},
    )

    # 기존 기사 검색은 서버 설정의 정부기관 직접 수집원을 계속 사용한다.
    payload = _base_payload(
        reportDate=report_date,
        enableYonhap=False,
        enableOpmPress=True,
        enableMePress=True,
        queries=[],
    )
    response = client.post("/api/collections", json=payload)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["rawCollectedCount"] == 4
    assert data["uniqueCount"] == 3

    listed = _articles(report_date)["data"]["articles"]
    article = next(item for item in listed if item["url"] == gov_item["url"])
    assert article["governmentPressRelease"] is True
    assert article["assessment"]["effectivePriority"] == "review"
    assert article["assessment"]["autoReasons"]["relevanceRank"] == 99
    assert "official_government_source" in article["assessment"]["autoReasons"]["appliedFloors"]
    excluded_article = next(item for item in listed if item["url"] == excluded_item["url"])
    assert excluded_article["governmentPressRelease"] is True
    previous_article = next(item for item in listed if item["url"] == previous_date_item["url"])
    assert previous_article["governmentPressRelease"] is True
    assert all(item["url"] != expired_item["url"] for item in listed)


def test_government_collection_does_not_fall_back_to_media_provider(monkeypatch):
    report_date = "2025-01-27"
    monkeypatch.setenv("POLICY_BRIEFING_SERVICE_KEY", "test-key")

    def fail_government(*args, **kwargs):
        raise CollectionHttpError("정부 수집원 장애")

    gdelt_called = False

    def track_gdelt(*args, **kwargs):
        nonlocal gdelt_called
        gdelt_called = True
        return []

    monkeypatch.setattr(collector_module, "fetch_policy_briefing", fail_government)
    monkeypatch.setattr(collector_module, "fetch_gdelt_combined", track_gdelt)
    payload = _base_payload(
        reportDate=report_date,
        enableYonhap=False,
        enableOpmPress=False,
        enableMePress=False,
        queries=[],
    )

    response = client.post("/api/government-press-releases/collections", json=payload)

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "failed"
    assert gdelt_called is False


def test_policy_briefing_button_saves_and_displays_every_returned_item(monkeypatch):
    report_date = "2025-01-28"
    monkeypatch.setenv("POLICY_BRIEFING_SERVICE_KEY", "test-key")
    items = [
        {
            "id": "raw-policy-1",
            "sourceId": "policy-briefing:900001",
            "title": "산업부 보도자료",
            "source": "산업통상자원부",
            "url": "https://www.korea.kr/briefing/pressReleaseView.do?newsId=900001",
            "pubDate": f"{report_date}T01:00:00Z",
            "description": "산업 정책 발표",
            "provider": "정책브리핑 API",
        },
        {
            "id": "raw-policy-2",
            "sourceId": "policy-briefing:900002",
            "title": "고용부 보도자료",
            "source": "고용노동부",
            "url": "https://www.korea.kr/briefing/pressReleaseView.do?newsId=900002",
            "pubDate": f"{report_date}T02:00:00Z",
            "description": "고용 정책 발표",
            "provider": "정책브리핑 API",
        },
    ]
    monkeypatch.setattr(
        collector_module,
        "fetch_policy_briefing",
        lambda *a, **k: {"items": items, "provider": "정책브리핑 API"},
    )
    payload = _base_payload(
        reportDate=report_date,
        enableYonhap=False,
        enableOpmPress=False,
        enableMePress=False,
        queries=[],
    )

    response = client.post("/api/government-press-releases/collections", json=payload)

    assert response.status_code == 200
    assert response.json()["data"]["uniqueCount"] == 2
    listed = _articles(report_date)["data"]["articles"]
    government = [item for item in listed if item["governmentPressRelease"]]
    assert {item["title"] for item in government} == {"산업부 보도자료", "고용부 보도자료"}


@pytest.mark.parametrize(
    ("report_date", "first_endpoint", "second_endpoint"),
    [
        ("2028-01-21", "/api/government-press-releases/collections", "/api/collections"),
        ("2028-03-22", "/api/collections", "/api/government-press-releases/collections"),
    ],
)
def test_media_and_government_collection_order_preserves_existing_articles(
    monkeypatch, report_date, first_endpoint, second_endpoint
):
    monkeypatch.setenv("POLICY_BRIEFING_SERVICE_KEY", "test-key")
    media_url = (
        "https://www.yna.co.kr/view/AKR"
        f"{report_date.replace('-', '')}0001-preserve-order"
    )
    government_url = (
        "https://www.korea.kr/briefing/pressReleaseView.do?newsId="
        f"{report_date.replace('-', '')}"
    )
    monkeypatch.setattr(
        collector_module,
        "fetch_yonhap_rss",
        lambda *a, **k: _yonhap_result(
            media_url,
            f"{report_date}T09:00:00Z",
            title=f"한국전기안전공사 {report_date} 수집 순서 보존 언론기사",
        ),
    )
    monkeypatch.setattr(collector_module, "fetch_google_rss", lambda *a, **k: [])
    monkeypatch.setattr(
        collector_module,
        "fetch_policy_briefing",
        lambda *a, **k: {
            "items": [
                {
                    "id": f"raw-policy-{report_date}",
                    "sourceId": f"policy-briefing:{report_date}",
                    "title": f"{report_date} 수집 순서 보존 정부 보도자료",
                    "source": "문화체육관광부",
                    "url": government_url,
                    "pubDate": f"{report_date}T08:00:00Z",
                    "description": "정부 정책 발표 원문",
                    "provider": "정책브리핑 API",
                }
            ],
            "provider": "정책브리핑 API",
        },
    )
    payload = _base_payload(
        reportDate=report_date,
        enableYonhap=True,
        enableOpmPress=False,
        enableMePress=False,
    )

    first = client.post(first_endpoint, json=payload)
    assert first.status_code == 200
    before = _articles(report_date)["data"]["articles"]
    assert len(before) == 1
    preserved = {
        key: before[0][key]
        for key in ("id", "title", "source", "url", "description", "governmentPressRelease")
    }

    second = client.post(second_endpoint, json=payload)
    assert second.status_code == 200
    after = _articles(report_date)["data"]["articles"]

    assert len(after) == 2
    assert preserved in [
        {
            key: article[key]
            for key in ("id", "title", "source", "url", "description", "governmentPressRelease")
        }
        for article in after
    ]
    assert {article["url"] for article in after} == {media_url, government_url}


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
