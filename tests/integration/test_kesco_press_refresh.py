from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.services.collection import kesco_press_cache

client = TestClient(app)


def test_kesco_press_refresh_is_separate_from_news_collection(monkeypatch):
    monkeypatch.setattr(
        kesco_press_cache,
        "fetch_kesco_press",
        lambda max_records=30: {
            "pressReleases": [
                {
                    "id": "kesco:refresh-991900",
                    "bbsSeq": "991900",
                    "title": "별도 갱신 API 보도자료",
                    "publishedAt": "2025-03-01T00:00:00Z",
                    "bodyText": "기사 검색과 분리해 저장하는 기준 원문입니다.",
                    "url": "https://www.kesco.or.kr/bbs/pr/selectBbs.do?bbs_code=MKB00002&bbs_seq=991900",
                    "fetchedAt": "2025-03-01T00:05:00Z",
                }
            ],
            "provider": "한국전기안전공사 보도자료",
            "warning": None,
        },
    )

    refreshed = client.post(
        "/api/kesco-press-releases/refresh", json={"maxRecords": 30}
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["data"]["refreshedCount"] == 1

    status = client.get("/api/kesco-press-releases/status")
    assert status.status_code == 200
    assert status.json()["data"]["releaseCount"] >= 1

    listed = client.get("/api/kesco-press-releases", params={"limit": 30})
    assert listed.status_code == 200
    release = next(
        item
        for item in listed.json()["data"]["pressReleases"]
        if item["id"] == "kesco:refresh-991900"
    )
    assert release["bodyText"] == "기사 검색과 분리해 저장하는 기준 원문입니다."
