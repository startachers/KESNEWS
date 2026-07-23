from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.repositories import dropped_article_repository as dropped_repo
from backend.app.repositories import run_repository as run_repo
from backend.app.repositories.database import get_connection

client = TestClient(app)


def _article(title: str, source: str) -> dict:
    return {
        "title": title,
        "url": f"https://news.example/{abs(hash(title)) % 100000}",
        "source": source,
        "pubDate": "2026-07-23T09:00:00Z",
        "description": "본문 요약",
        "category": "uncategorized",
    }


def _seed_pool(report_date: str, articles: list[dict]) -> None:
    connection = get_connection()
    try:
        with connection:
            run_id = run_repo.create_run(
                connection,
                report_date=report_date,
                started_at="2026-07-23T08:00:00Z",
                lookback_hours=24,
            )
            dropped_repo.replace_for_run(
                connection,
                collection_run_id=run_id,
                report_date=report_date,
                articles=articles,
            )
    finally:
        connection.close()


def test_discovered_issues_returns_big_event_and_excludes_entertainment():
    report_date = "2026-07-23"
    fire = [
        _article("경남 창원 공장 화재로 2명 사망", "한겨레"),
        _article("경남 창원 공장 화재…2명 숨져", "중앙일보"),
        _article("경남 창원 공장 화재 사망자 2명 확인", "동아일보"),
        _article("경남 창원 공장 화재 원인 조사 착수", "경향신문"),
        _article("경남 창원 공장 화재 소방 대응 2단계", "서울신문"),
    ]
    entertainment = [
        _article("인기 아이돌 그룹 컴백 무대 화제", "스포츠서울"),
        _article("아이돌 그룹 신곡 컴백 성공", "스포츠조선"),
        _article("아이돌 컴백 팬미팅 매진 행렬", "일간스포츠"),
        _article("아이돌 그룹 앨범 판매 신기록", "OSEN"),
        _article("아이돌 컴백 방송 출연 확정", "마이데일리"),
    ]
    _seed_pool(report_date, [*fire, *entertainment, _article("환율 소폭 상승 마감", "매경")])

    response = client.get(f"/api/collections/discovered-issues?report_date={report_date}")
    assert response.status_code == 200
    data = response.json()["data"]

    assert data["pooledCount"] == 11
    assert len(data["issues"]) == 1
    issue = data["issues"][0]
    assert "창원" in issue["title"]
    assert issue["articleCount"] == 5
    assert len(issue["articles"]) == 5


def test_discovered_issues_empty_when_no_pool():
    response = client.get("/api/collections/discovered-issues?report_date=2000-01-01")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["pooledCount"] == 0
    assert data["issues"] == []


def test_discovered_issue_articles_can_be_imported_grouped_and_trimmed():
    # 실행 당일 작업본을 만드는 daily-reset 회귀와 순서 의존 충돌하지 않는 고정 미래 날짜다.
    report_date = "2096-07-24"
    briefing = client.put(
        f"/api/briefings/{report_date}",
        json={"expectedRevision": 0, "patch": {}},
    ).json()["data"]
    articles = [
        _article(f"인천 물류센터 화재 진화 작업 {index}", f"매체{index}")
        for index in range(5)
    ]
    _seed_pool(report_date, articles)
    issue = client.get(
        "/api/collections/discovered-issues",
        params={"report_date": report_date},
    ).json()["data"]["issues"][0]

    imported_ids = []
    for article in issue["articles"]:
        imported = client.post(
            "/api/articles",
            json={
                "reportDate": report_date,
                "title": article["title"],
                "source": article["source"],
                "url": article["url"],
                "pubDate": article["publishedAt"],
                "category": "other",
                "forcedRisk": "auto",
            },
        )
        assert imported.status_code == 200
        imported_ids.append(imported.json()["data"]["id"])

    grouped = client.post(
        "/api/issues/manual-group",
        json={
            "reportDate": report_date,
            "articleIds": imported_ids,
            "expectedRevision": briefing["revision"],
        },
    )
    assert grouped.status_code == 200
    grouped_data = grouped.json()["data"]
    assert grouped_data["issue"]["manualGroup"] is True
    assert set(grouped_data["issue"]["articleIds"]) == set(imported_ids)

    trimmed = client.patch(
        f"/api/briefings/{report_date}/issues/{grouped_data['issue']['id']}",
        json={
            "expectedRevision": grouped_data["revision"],
            "articleId": imported_ids[-1],
            "membershipAction": "remove",
        },
    )
    assert trimmed.status_code == 200
    visible = client.get(
        "/api/issues",
        params={"report_date": report_date},
    ).json()["data"]["issues"]
    saved_group = next(item for item in visible if item["id"] == grouped_data["issue"]["id"])
    assert imported_ids[-1] not in saved_group["articleIds"]
    assert set(imported_ids[:-1]).issubset(saved_group["articleIds"])


def test_overlapping_discovered_import_extends_existing_group_without_replacing_it():
    report_date = "2026-07-25"
    briefing = client.put(
        f"/api/briefings/{report_date}",
        json={"expectedRevision": 0, "patch": {}},
    ).json()["data"]

    article_ids = []
    for index in range(3):
        created = client.post(
            "/api/articles",
            json={
                "reportDate": report_date,
                "title": f"기존 브리핑 중복 이슈 기사 {index}",
                "source": f"매체{index}",
                "url": f"https://news.example/existing-issue/{index}",
                "category": "other",
            },
        )
        assert created.status_code == 200
        article_ids.append(created.json()["data"]["id"])

    grouped = client.post(
        "/api/issues/manual-group",
        json={
            "reportDate": report_date,
            "articleIds": article_ids[:2],
            "expectedRevision": briefing["revision"],
        },
    ).json()["data"]
    issue_id = grouped["issue"]["id"]

    extended = client.patch(
        f"/api/briefings/{report_date}/issues/{issue_id}",
        json={
            "expectedRevision": grouped["revision"],
            "articleId": article_ids[2],
            "membershipAction": "add",
        },
    )
    assert extended.status_code == 200

    issues = client.get(
        "/api/issues",
        params={"report_date": report_date},
    ).json()["data"]["issues"]
    manual_groups = [issue for issue in issues if issue["manualGroup"]]
    assert len(manual_groups) == 1
    assert manual_groups[0]["id"] == issue_id
    assert set(manual_groups[0]["articleIds"]) == set(article_ids)
