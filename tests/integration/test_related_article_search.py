from fastapi.testclient import TestClient

from backend.app.main import app


client = TestClient(app)


def test_related_search_adds_at_most_ten_articles_to_original_issue(monkeypatch):
    monkeypatch.delenv("NAVER_CLIENT_ID", raising=False)
    monkeypatch.delenv("NAVER_CLIENT_SECRET", raising=False)
    report_date = "2097-01-15"
    created = client.put(
        f"/api/briefings/{report_date}", json={"expectedRevision": 0, "patch": {}}
    )
    assert created.status_code == 200
    revision = created.json()["data"]["revision"]
    original = client.post(
        "/api/articles",
        json={
            "reportDate": report_date,
            "title": "전주 변전소 침수 대비 안전점검 결과 발표",
            "source": "연합뉴스",
            "url": "https://original.example.com/substation",
            "pubDate": f"{report_date}T01:00:00Z",
            "description": "변전소 침수 대비 안전점검 결과와 후속 대책을 발표했다.",
            "category": "safety",
        },
    )
    assert original.status_code == 200
    article_id = original.json()["data"]["id"]
    revision = client.get(f"/api/briefings/{report_date}").json()["data"]["revision"]
    searched = [
        {
            "title": f"변전소 침수 안전점검 후속 보도 {index}",
            "source": "연합뉴스",
            "url": f"https://www.yna.co.kr/view/related-{index}",
            "pubDate": f"{report_date}T{index:02d}:00:00Z",
            "description": "관계기관이 변전소 침수 안전점검 후속 대책을 밝혔다.",
            "publisherId": "yonhap",
            "publisherAllowed": True,
        }
        for index in range(12)
    ]
    monkeypatch.setattr(
        "backend.app.services.collection.related_search.search_related_candidates",
        lambda article, **kwargs: searched,
    )

    response = client.post(
        f"/api/briefings/{report_date}/articles/{article_id}/related-search",
        json={"expectedRevision": revision},
    )

    assert response.status_code == 200, response.json()
    data = response.json()["data"]
    assert data["foundCount"] == 10
    assert data["addedCount"] == 10
    assert data["revision"] == revision + 1
    assert data["policy"]["maxResults"] == 10
    issues = client.get("/api/issues", params={"report_date": report_date}).json()["data"]["issues"]
    issue = next(item for item in issues if item["id"] == data["issueId"])
    assert len(issue["articleIds"]) == 11
    articles = client.get("/api/articles", params={"report_date": report_date}).json()["data"]["articles"]
    assert len(articles) == 11


def test_related_search_preserves_revision_when_nothing_is_found(monkeypatch):
    monkeypatch.delenv("NAVER_CLIENT_ID", raising=False)
    monkeypatch.delenv("NAVER_CLIENT_SECRET", raising=False)
    report_date = "2097-01-16"
    client.put(f"/api/briefings/{report_date}", json={"expectedRevision": 0, "patch": {}})
    original = client.post(
        "/api/articles",
        json={
            "reportDate": report_date,
            "title": "전기설비 안전관리 점검",
            "source": "테스트언론",
            "url": "https://original.example.com/no-result",
            "pubDate": f"{report_date}T01:00:00Z",
            "description": "전기설비 안전관리 점검",
            "category": "safety",
        },
    ).json()["data"]
    revision = client.get(f"/api/briefings/{report_date}").json()["data"]["revision"]
    monkeypatch.setattr(
        "backend.app.services.collection.related_search.search_related_candidates",
        lambda article, **kwargs: [],
    )

    response = client.post(
        f"/api/briefings/{report_date}/articles/{original['id']}/related-search",
        json={"expectedRevision": revision},
    )

    assert response.status_code == 200
    assert response.json()["data"]["foundCount"] == 0
    assert response.json()["data"]["revision"] == revision


def test_related_search_failure_preserves_existing_work(monkeypatch):
    monkeypatch.delenv("NAVER_CLIENT_ID", raising=False)
    monkeypatch.delenv("NAVER_CLIENT_SECRET", raising=False)
    report_date = "2097-01-17"
    client.put(f"/api/briefings/{report_date}", json={"expectedRevision": 0, "patch": {}})
    original = client.post(
        "/api/articles",
        json={
            "reportDate": report_date,
            "title": "변전소 안전점검 실패 보존 시험",
            "source": "테스트언론",
            "url": "https://original.example.com/search-error",
            "pubDate": f"{report_date}T01:00:00Z",
            "description": "기존 메모와 선정 상태를 보존한다.",
            "category": "safety",
        },
    ).json()["data"]
    revision = client.get(f"/api/briefings/{report_date}").json()["data"]["revision"]
    monkeypatch.setattr(
        "backend.app.services.collection.related_search.search_related_candidates",
        lambda article, **kwargs: (_ for _ in ()).throw(RuntimeError("provider unavailable")),
    )

    response = client.post(
        f"/api/briefings/{report_date}/articles/{original['id']}/related-search",
        json={"expectedRevision": revision},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "RELATED_ARTICLE_SEARCH_FAILED"
    saved = client.get(f"/api/briefings/{report_date}").json()["data"]
    assert saved["revision"] == revision
    articles = client.get("/api/articles", params={"report_date": report_date}).json()["data"]["articles"]
    assert [item["id"] for item in articles] == [original["id"]]
