from backend.app.services.classification.sentinel import detect_incident_sentinel
from backend.app.services.classification.service import classify_article, get_relevance
from backend.app.services.collection.collector import apply_collection_limit
from backend.app.services.collection import yonhap as yonhap_module


def test_major_fire_without_numbers_is_preserved_with_null_values():
    article = {"title": "창고 화재, 피해 규모 파악 중", "description": "소방당국이 진화 중이다."}
    result = detect_incident_sentinel(article)

    assert result["matched"] is True
    assert result["incident"] == {
        "incident_type": "fire",
        "cause_status": "unknown",
        "incident_status": "breaking",
        "deaths": None,
        "injuries": None,
        "property_damage_krw": None,
        "critical_facility": None,
    }
    assert get_relevance(article)["rank"] == 3


def test_outage_extracts_households_and_duration_but_keeps_unknowns_nullable():
    result = detect_incident_sentinel(
        {"title": "아파트 1,500세대 정전", "description": "승강기 멈춰 2시간 30분 만에 복구"}
    )

    assert result["matched"] is True
    assert result["incident"]["households"] == 1500
    assert result["incident"]["duration_minutes"] == 150
    assert result["incident"]["planned"] is False


def test_planned_outage_notice_without_actual_accident_is_excluded():
    result = detect_incident_sentinel(
        {"title": "정기점검에 따른 계획정전 안내", "description": "아파트 500세대 대상 정전 예정"}
    )

    assert result == {"matched": False, "incident": None}


def test_insurance_company_record_earnings_is_not_a_fire_incident():
    result = detect_incident_sentinel(
        {"title": "삼성화재, 2분기 사상 최대 실적 전망", "description": "목표가 상향"}
    )
    assert result == {"matched": False, "incident": None}


def test_fire_evacuation_call_promotion_is_not_a_fire_incident():
    result = detect_incident_sentinel(
        {"title": "노원소방서, 119화재대피안심콜 홍보 강화", "description": "가입 홍보"}
    )
    assert result == {"matched": False, "incident": None}


def test_industrial_accident_statistics_are_not_breaking_fire_incident():
    result = detect_incident_sentinel(
        {"title": "산재사망 역대 최저…화재·폭발 제조업선 증가", "description": "상반기 통계"}
    )
    assert result == {"matched": False, "incident": None}


def test_fire_sentinel_relevance_reason_is_not_power_outage():
    article = {"title": "공장 화재로 1명 사망", "description": ""}
    relevance = get_relevance(article)
    assert relevance["rank"] == 3
    assert relevance["reasons"] == ["③ 중대화재 Sentinel"]


def test_collection_limit_keeps_sentinel_and_rank_one_before_other_articles():
    sentinel = classify_article({"id": "sentinel", "title": "공장 화재 1명 사망", "description": ""})
    direct = classify_article({"id": "direct", "title": "한국전기안전공사 새 소식", "description": ""})
    ordinary = classify_article({"id": "ordinary", "title": "대통령 전력망 확충 주문", "description": ""})

    limited = apply_collection_limit([ordinary, sentinel, direct], 2)

    assert {item["id"] for item in limited} == {"sentinel", "direct"}


def test_yonhap_keeps_sentinel_that_would_miss_text_relevance_without_sentinel(monkeypatch):
    monkeypatch.setattr(yonhap_module, "http_get", lambda *args: (200, "rss"))
    monkeypatch.setattr(
        yonhap_module,
        "parse_rss_items",
        lambda *args: [
            {
                "id": "breaking-fire",
                "title": "창고 화재, 피해 규모 파악 중",
                "description": "큰불을 진화하고 있다.",
                "pubDate": None,
            },
            {"id": "unrelated", "title": "지역 문화행사", "description": "", "pubDate": None},
        ],
    )

    result = yonhap_module.fetch_yonhap_rss(lambda value: True, 10)

    assert [item["id"] for item in result["items"]] == ["breaking-fire"]
    assert result["items"][0]["_sentinel"]["matched"] is True
