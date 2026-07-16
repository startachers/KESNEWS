import pytest

from backend.app.services.classification.rule_engine import infer_category, should_exclude
from backend.app.services.classification.service import (
    CLASSIFIER_VERSION,
    assess_article,
    classify_article,
    get_relevance,
)

RISK_KEYWORDS = ["사망", "화재", "감전", "국정감사", "감사"]
POSITIVE_KEYWORDS = ["캠페인", "수상"]


@pytest.mark.parametrize(
    ("description", "rank", "score", "category"),
    [
        ("한국전기안전공사 새 소식", 1, 100, "kesco_direct"),
        ("작업자가 감전 사고를 당했다", 2, 88, "electrical_accident"),
        ("아파트 일대 정전이 발생했다", 3, 80, "power_outage"),
        ("대통령이 전력망 확충을 주문했다", 4, 65, "presidential_message"),
        ("전기안전관리법 개정이 발표됐다", 5, 55, "law_standard_plan"),
        ("공공기관 경영평가 결과가 발표됐다", 6, 45, "public_evaluation"),
        ("ESS 배터리 화재 안전대책이 나왔다", 7, 40, "new_industry_safety"),
    ],
)
def test_rules_v3_relevance_rank_and_category(description, rank, score, category):
    article = {"title": "관련 소식", "description": description}
    relevance = get_relevance(article)
    assert relevance["rank"] == rank
    assert relevance["score"] == score
    assert infer_category(article) == category


def test_classifier_version_is_rules_v3():
    assert CLASSIFIER_VERSION == "rules-v3"


def test_classify_article_critical_risk_from_heavy_keyword():
    raw = {"title": "공장 화재로 1명 사망", "description": "야간 화재로 근로자 1명이 사망했다."}
    result = classify_article(raw, RISK_KEYWORDS, POSITIVE_KEYWORDS)
    # 중대화재 Sentinel은 전기 원인 확인 전에도 rank 3으로 보존한다.
    assert result["risk"] == "critical"
    assert result["assessment"]["autoReasons"]["relevanceRank"] == 3
    assert result["assessment"]["incident"]["cause_status"] == "unknown"
    assert result["assessment"]["autoSeverityScore"] == 100
    assert "low_relevance_cap" not in result["assessment"]["autoReasons"]["appliedCaps"]
    assert result["sentiment"] == "negative"
    assert "사망" in result["matchedKeywords"]


def test_classify_article_routine_when_no_keywords_match():
    raw = {"title": "전기안전 교육 실시", "description": "지역 주민 대상 전기안전 교육을 실시했다."}
    result = classify_article(raw, RISK_KEYWORDS, POSITIVE_KEYWORDS)
    assert result["risk"] == "routine"
    assert result["sentiment"] == "neutral"


def test_classify_article_positive_sentiment_without_risk_keywords():
    raw = {"title": "안전 캠페인으로 수상", "description": "전기안전 캠페인이 우수 사례로 수상했다."}
    result = classify_article(raw, RISK_KEYWORDS, POSITIVE_KEYWORDS)
    assert result["sentiment"] == "positive"
    assert result["risk"] == "routine"


def test_classify_article_preserves_manual_and_defaults_included():
    raw = {"title": "제목", "manual": True}
    result = classify_article(raw, RISK_KEYWORDS, POSITIVE_KEYWORDS)
    assert result["manual"] is True
    assert result["included"] is True  # manual 기사는 기본 included=True


def test_classify_article_respects_explicit_included_false():
    raw = {"title": "제목", "manual": True, "included": False}
    result = classify_article(raw, RISK_KEYWORDS, POSITIVE_KEYWORDS)
    assert result["included"] is False


def test_infer_category_matches_safety_keyword():
    assert infer_category({"title": "전기화재 발생", "description": ""}) == "electrical_accident"


def test_infer_category_defaults_to_direct():
    assert infer_category({"title": "관계없는 제목", "description": "무관한 내용"}) == "kesco_direct"


def test_should_exclude_matches_keyword():
    assert should_exclude({"title": "채용공고 안내", "description": ""}, ["채용공고"]) is True
    assert should_exclude({"title": "정상 기사", "description": ""}, ["채용공고"]) is False


def test_get_relevance_ranks_agency_mention_highest():
    result = get_relevance({"title": "한국전기안전공사 국정감사 출석", "description": ""})
    assert result["rank"] == 1
    assert result["score"] == 100


def test_get_relevance_no_match_returns_rank_99():
    result = get_relevance({"title": "오늘의 날씨", "description": "전국 대체로 맑음"})
    assert result["rank"] == 99
    assert result["score"] == 15


def test_official_government_source_has_review_floor_without_becoming_required():
    result = assess_article(
        {
            "title": "정례 브리핑 자료",
            "description": "담당 부서 안내",
            "_official_government": True,
        }
    )
    assert result["autoReasons"]["relevanceRank"] == 99
    assert result["autoPriority"] == "review"
    assert "official_government_source" in result["autoReasons"]["appliedFloors"]


def test_prevention_phrase_does_not_become_accident():
    result = assess_article(
        {"title": "한국전기안전공사, 전기화재 예방 캠페인", "description": "안전점검 교육을 실시했다."}
    )
    assert result["autoEventType"] == "prevention"
    assert result["autoCategory"] == "kesco_achievement"
    assert result["autoPriority"] != "required"
    assert "positive_context_cap" in result["autoReasons"]["appliedCaps"]


def test_actual_accident_is_not_suppressed_by_prevention_sentence():
    result = assess_article(
        {
            "title": "한국전기안전공사 전기화재 예방 당부",
            "description": "공장 전기화재가 발생해 1명이 사망했다.",
        }
    )
    assert result["autoEventType"] == "mixed"
    assert result["autoSeverityScore"] == 100
    assert result["autoPriority"] == "required"
    assert "direct_serious_adverse" in result["autoReasons"]["appliedFloors"]


def test_badge_audit_token_is_suppressed_but_audit_office_phrase_survives():
    badge = assess_article({"title": "한국전기안전공사 감사패 전달", "description": "감사 인사를 전했다."})
    assert badge["autoEventType"] == "general"
    assert badge["autoCategory"] != "management"

    audit = assess_article(
        {"title": "한국전기안전공사 감사패 전달 뒤 감사원 감사 착수", "description": "감사가 시작됐다."}
    )
    assert audit["autoEventType"] == "management_risk"
    assert audit["autoCategory"] == "kesco_governance"
    assert audit["autoPriority"] == "required"
    assert "direct_audit_or_legal" in audit["autoReasons"]["appliedFloors"]


def test_electrical_casualty_without_direct_mention_has_review_floor():
    result = assess_article(
        {"title": "전기화재 발생으로 사망자 발생", "description": "공장 전기 화재로 2명이 사망했다."}
    )
    assert result["autoRelevanceScore"] >= 40
    assert result["autoPriority"] in {"review", "required"}
    assert "electrical_safety_casualty" in result["autoReasons"]["appliedFloors"]


def test_low_relevance_electrical_casualty_overrides_reference_cap():
    result = assess_article(
        {"title": "누전 사고 발생으로 2명 사망", "description": "지하 작업장에서 인명피해가 발생했다."}
    )
    assert result["autoRelevanceScore"] < 40
    assert "low_relevance_cap" in result["autoReasons"]["appliedCaps"]
    assert result["autoPriority"] == "review"
    assert "electrical_safety_casualty" in result["autoReasons"]["appliedFloors"]
