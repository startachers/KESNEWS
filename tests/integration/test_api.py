from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)


def _create_briefing(report_date: str) -> dict:
    response = client.put(f"/api/briefings/{report_date}", json={"expectedRevision": 0, "patch": {}})
    assert response.status_code == 200
    return response.json()["data"]


def test_put_briefing_creates_then_updates_with_revision_check():
    briefing = _create_briefing("2026-07-15")
    assert briefing["reportDate"] == "2026-07-15"
    assert briefing["revision"] == 1
    assert briefing["status"] == "draft"

    updated = client.put(
        "/api/briefings/2026-07-15",
        json={"expectedRevision": 1, "patch": {"actionNote": "지시사항 메모"}},
    )
    assert updated.status_code == 200
    body = updated.json()["data"]
    assert body["actionNote"] == "지시사항 메모"
    assert body["revision"] == 2


def test_put_briefing_rejects_stale_revision():
    _create_briefing("2026-07-16")
    stale = client.put(
        "/api/briefings/2026-07-16",
        json={"expectedRevision": 99, "patch": {"actionNote": "충돌"}},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "BRIEFING_REVISION_CONFLICT"


def test_get_briefing_not_found_returns_404():
    response = client.get("/api/briefings/2099-01-01")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "BRIEFING_NOT_FOUND"


def test_manual_article_add_then_patch_survives_reload():
    _create_briefing("2026-07-17")
    created = client.post(
        "/api/articles",
        json={
            "reportDate": "2026-07-17",
            "title": "전기화재 예방 캠페인 실시",
            "source": "테스트일보",
            "url": "https://example.com/news/1",
            "description": "설명",
            "category": "safety",
            "riskKeywords": ["화재"],
        },
    )
    assert created.status_code == 200
    article_id = created.json()["data"]["id"]

    listed = client.get("/api/articles", params={"report_date": "2026-07-17"})
    assert listed.status_code == 200
    items = listed.json()["data"]["articles"]
    assert any(item["id"] == article_id and item["included"] is True for item in items)

    briefing = client.get("/api/briefings/2026-07-17").json()["data"]
    patched = client.patch(
        f"/api/briefings/2026-07-17/articles/{article_id}",
        json={"expectedRevision": briefing["revision"], "starred": True, "note": "중요 메모"},
    )
    assert patched.status_code == 200
    assert patched.json()["data"]["revision"] == briefing["revision"] + 1

    reloaded = client.get("/api/articles", params={"report_date": "2026-07-17"}).json()["data"]["articles"]
    reloaded_article = next(item for item in reloaded if item["id"] == article_id)
    assert reloaded_article["starred"] is True
    assert reloaded_article["note"] == "중요 메모"
    assert reloaded_article["included"] is True


def test_patch_dismissed_normalizes_selected_to_false_and_preserves_note():
    _create_briefing("2026-07-18")
    created = client.post(
        "/api/articles",
        json={
            "reportDate": "2026-07-18",
            "title": "지역 상생 협약 체결",
            "source": "테스트경제",
            "url": "https://example.com/news/2",
            "description": "설명",
            "category": "community",
        },
    )
    article_id = created.json()["data"]["id"]
    briefing = client.get("/api/briefings/2026-07-18").json()["data"]

    client.patch(
        f"/api/briefings/2026-07-18/articles/{article_id}",
        json={"expectedRevision": briefing["revision"], "note": "보존돼야 하는 메모"},
    )
    briefing = client.get("/api/briefings/2026-07-18").json()["data"]

    dismissed = client.patch(
        f"/api/briefings/2026-07-18/articles/{article_id}",
        json={"expectedRevision": briefing["revision"], "dismissed": True},
    )
    assert dismissed.status_code == 200

    default_list = client.get("/api/articles", params={"report_date": "2026-07-18"}).json()["data"]["articles"]
    assert not any(item["id"] == article_id for item in default_list)

    with_dismissed = client.get(
        "/api/articles", params={"report_date": "2026-07-18", "include_dismissed": True}
    ).json()["data"]["articles"]
    dismissed_article = next(item for item in with_dismissed if item["id"] == article_id)
    assert dismissed_article["included"] is False
    assert dismissed_article["dismissed"] is True
    assert dismissed_article["note"] == "보존돼야 하는 메모"


def test_delete_manual_article_requires_confirm_and_no_cross_date_reference():
    _create_briefing("2026-07-19")
    created = client.post(
        "/api/articles",
        json={
            "reportDate": "2026-07-19",
            "title": "삭제 대상 수동 기사",
            "source": "테스트신문",
            "url": "https://example.com/news/3",
        },
    )
    article_id = created.json()["data"]["id"]

    without_confirm = client.delete(f"/api/articles/{article_id}")
    assert without_confirm.status_code == 409
    assert without_confirm.json()["error"]["code"] == "ARTICLE_IN_USE"

    deleted = client.delete(f"/api/articles/{article_id}", params={"confirm": True})
    assert deleted.status_code == 200

    missing = client.delete(f"/api/articles/{article_id}", params={"confirm": True})
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "ARTICLE_NOT_FOUND"


def test_article_order_reassigns_sort_order_for_listed_ids_only():
    _create_briefing("2026-07-20")
    ids = []
    for index in range(3):
        created = client.post(
            "/api/articles",
            json={
                "reportDate": "2026-07-20",
                "title": f"정렬 테스트 기사 {index}",
                "source": "테스트일보",
                "url": f"https://example.com/order/{index}",
            },
        )
        ids.append(created.json()["data"]["id"])

    briefing = client.get("/api/briefings/2026-07-20").json()["data"]
    reordered = client.put(
        "/api/briefings/2026-07-20/article-order",
        json={"expectedRevision": briefing["revision"], "articleIds": [ids[2], ids[0], ids[1]]},
    )
    assert reordered.status_code == 200

    items = client.get("/api/articles", params={"report_date": "2026-07-20"}).json()["data"]["articles"]
    order_by_id = {item["id"]: item["sortOrder"] for item in items}
    assert order_by_id[ids[2]] == 0
    assert order_by_id[ids[0]] == 1
    assert order_by_id[ids[1]] == 2


def test_patch_assessment_final_values_and_clear_manual_override():
    _create_briefing("2026-07-21")
    created = client.post(
        "/api/articles",
        json={
            "reportDate": "2026-07-21",
            "title": "한국전기안전공사 전기화재 예방 점검",
            "source": "테스트일보",
            "url": "https://example.com/assessment/1",
            "category": "safety",
        },
    )
    article_id = created.json()["data"]["id"]

    patched = client.patch(
        f"/api/articles/{article_id}/assessment",
        json={"finalPriority": "required", "finalEventType": "management_risk"},
    )
    assert patched.status_code == 200
    assessment = patched.json()["data"]
    assert assessment["manualOverride"] is True
    assert assessment["effectivePriority"] == "required"
    assert assessment["effectiveEventType"] == "management_risk"

    reclassified = client.post(
        "/api/articles",
        json={
            "reportDate": "2026-07-21",
            "title": "한국전기안전공사 전기화재 예방 점검",
            "source": "테스트일보",
            "url": "https://example.com/assessment/1",
            "category": "safety",
        },
    )
    assert reclassified.status_code == 200
    after_reclassification = client.patch(
        f"/api/articles/{article_id}/assessment", json={}
    ).json()["data"]
    assert after_reclassification["finalPriority"] == "required"
    assert after_reclassification["finalEventType"] == "management_risk"
    assert after_reclassification["manualOverride"] is True

    listed = client.get("/api/articles", params={"report_date": "2026-07-21"}).json()["data"]["articles"]
    article = next(item for item in listed if item["id"] == article_id)
    assert article["priority"] == "required"
    assert article["risk"] == "critical"

    cleared = client.patch(
        f"/api/articles/{article_id}/assessment",
        json={"finalCategory": None, "finalEventType": None, "finalPriority": None, "finalTone": None},
    )
    assert cleared.status_code == 200
    cleared_assessment = cleared.json()["data"]
    assert cleared_assessment["manualOverride"] is False
    assert cleared_assessment["effectivePriority"] == cleared_assessment["autoPriority"]


def test_patch_assessment_rejects_invalid_enum_and_missing_article():
    invalid = client.patch(
        "/api/articles/missing/assessment", json={"finalPriority": "urgent"}
    )
    assert invalid.status_code == 422

    missing = client.patch(
        "/api/articles/missing/assessment", json={"finalPriority": "review"}
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "ARTICLE_NOT_FOUND"


def test_manual_article_forced_risk_is_stored_as_final_priority():
    _create_briefing("2026-07-22")
    created = client.post(
        "/api/articles",
        json={
            "reportDate": "2026-07-22",
            "title": "일상 안전교육 안내",
            "source": "테스트일보",
            "url": "https://example.com/assessment/forced",
            "forcedRisk": "critical",
        },
    )
    assert created.status_code == 200
    article_id = created.json()["data"]["id"]
    article = next(
        item
        for item in client.get(
            "/api/articles", params={"report_date": "2026-07-22"}
        ).json()["data"]["articles"]
        if item["id"] == article_id
    )
    assert article["assessment"]["manualOverride"] is True
    assert article["assessment"]["finalPriority"] == "required"
    assert article["priority"] == "required"
    assert article["risk"] == "critical"
