from backend.app.services.classification.rule_engine import infer_category, should_exclude
from backend.app.services.classification.service import classify_article, get_relevance

RISK_KEYWORDS = ["사망", "화재", "감전", "국정감사", "감사"]
POSITIVE_KEYWORDS = ["캠페인", "수상"]


def test_classify_article_critical_risk_from_heavy_keyword():
    raw = {"title": "공장 화재로 1명 사망", "description": "야간 화재로 근로자 1명이 사망했다."}
    result = classify_article(raw, RISK_KEYWORDS, POSITIVE_KEYWORDS)
    assert result["risk"] == "critical"
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
    assert infer_category({"title": "전기화재 발생", "description": ""}) == "safety"


def test_infer_category_defaults_to_direct():
    assert infer_category({"title": "관계없는 제목", "description": "무관한 내용"}) == "direct"


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
    assert result["score"] == 0
