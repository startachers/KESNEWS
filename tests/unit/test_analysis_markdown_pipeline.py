import sqlite3

from backend.app.services.analysis_markdown.budget import truncate_at_sentence
from backend.app.services.analysis_markdown.eligibility import evaluate
from backend.app.services.analysis_markdown.quality import publisher_statistics
from backend.app.services.analysis_markdown.replacement_finder import find_replacement
from backend.app.services.extraction.cleaner import clean_article_text


CONFIG = {
    "minimum_full_text_characters": 500,
    "minimum_rss_summary_characters": 120,
    "official_document_minimum_characters": 180,
    "publisher_quality": {
        "evaluation_window": 20,
        "warning_success_rate": 0.8,
        "quarantine_success_rate": 0.6,
        "minimum_attempts_for_quarantine": 10,
    },
    "disabled_publishers": [],
    "cleaning_rule_version": "article-clean-v2.1",
}


def test_cleaner_removes_publisher_ai_and_recommendations_without_rewriting_facts():
    facts = (
        "지난 2월 화재가 발생해 고등학생 1명이 사망했다. 소방 보고서는 원인 미상으로 종결됐다. "
        "관계자는 전기적 원인으로 추정될 뿐 정확한 원인은 밝혀지지 않았다고 말했다. "
        "무자격 작업자의 배선 공사가 영향을 미쳤을 가능성이 있다. 전문가도 조사 필요성을 말했다."
    )
    result = clean_article_text(
        facts + " 핵심요약 쏙 AI 요약입니다. AI 해설 Key Points 시나리오별 전망 출처 목록 추천기사"
    )
    assert result.text == facts
    assert result.ai_content_detected is True
    assert "AI 해설" not in result.text
    assert "1명" in result.text
    assert "원인 미상" in result.text
    assert "가능성" in result.text


def test_cleaner_keeps_ai_word_when_it_is_an_ordinary_article_sentence():
    text = "정부는 산업 현장의 AI 분석 기술을 점검했다고 밝혔다. 후속 계획은 7월 발표한다."
    assert clean_article_text(text).text == text


def test_eligibility_rejects_navigation_and_short_text_but_accepts_factual_rss():
    navigation = clean_article_text(("많이 본 뉴스 로그인 메뉴 기사목록 좋아요 응원해요 " * 20))
    assert evaluate(navigation, status="success_full", url="https://kbs.co.kr/a", config=CONFIG).reason == "navigation_only"
    short = clean_article_text("짧은 기사")
    assert evaluate(short, status="success_full", url="https://example.com/a", config=CONFIG).reason == "body_too_short"
    summary = clean_article_text("7월 20일 정부는 전기요금 시간 차등제를 검토한다고 밝혔으며 구체적 적용 대상과 시범사업 계획, 향후 일정과 소비자 영향 등을 관계기관과 논의하고 있다고 설명했다. " * 2)
    assert evaluate(summary, status="success_summary", url="https://news1.kr/a", config=CONFIG).eligible


def test_budget_stops_at_complete_sentence():
    text = "첫 번째 문장입니다. 두 번째 문장은 조금 더 깁니다. 세 번째 문장입니다."
    reduced, changed = truncate_at_sentence(text, 35)
    assert changed is True
    assert reduced.endswith(".")
    assert "세 번째" not in reduced


def test_budget_keeps_an_over_limit_first_sentence_instead_of_silently_dropping_it():
    text = ("필수 기사에서 확인된 하나의 긴 완결 문장입니다 " * 15).strip() + "."
    reduced, changed = truncate_at_sentence(text, 60)
    assert changed is True
    assert reduced == text
    assert reduced.endswith(".")


def test_replacement_requires_same_issue_or_strong_event_match_and_preserves_id():
    original = {"id": "A", "title": "은마아파트 화재 원인 조사", "pubDate": "2026-07-20T01:00:00Z"}
    same = {"id": "B", "title": "은마아파트 화재 조사 결과", "pubDate": "2026-07-20T02:00:00Z", "publisherAllowed": True, "analysisEligible": True}
    other = {"id": "C", "title": "인천 물류센터 화재 진화", "pubDate": "2026-07-20T02:00:00Z", "publisherAllowed": True, "analysisEligible": True}
    found = find_replacement(original, [other, same], issue_ids_by_article={"A": {"I1"}, "B": {"I1"}, "C": {"I2"}})
    assert found["id"] == "B"
    assert find_replacement(original, [other], issue_ids_by_article={"A": {"I1"}, "C": {"I2"}}) is None


def test_publisher_quality_warning_and_quarantine_calculation():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("""CREATE TABLE publisher_extraction_events (
        id TEXT, article_id TEXT, publisher_id TEXT, publisher_name TEXT,
        extraction_status TEXT, analysis_eligible INTEGER, noise_detected INTEGER,
        ai_content_detected INTEGER, access_blocked INTEGER, failure_reason TEXT,
        attempted_at TEXT, cleaning_rule_version TEXT)""")
    for index in range(10):
        connection.execute(
            "INSERT INTO publisher_extraction_events VALUES (?, 'a', 'bad', '나쁜언론', 'failed', 0, 0, 0, 1, 'access_blocked', ?, 'article-clean-v2.1')",
            (str(index), f"2026-07-{index + 1:02d}"),
        )
    connection.execute("INSERT INTO publisher_extraction_events VALUES ('x', 'a', 'new', '신규언론', 'success_full', 1, 0, 0, 0, NULL, '2026-07-20', 'article-clean-v2.1')")
    stats = {item["publisherId"]: item for item in publisher_statistics(connection, CONFIG)}
    assert stats["bad"]["status"] == "quarantine"
    assert stats["new"]["status"] == "warning"
