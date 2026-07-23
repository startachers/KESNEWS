import sqlite3

from backend.app.services.analysis_markdown.budget import truncate_at_sentence
from backend.app.services.analysis_markdown.eligibility import evaluate
from backend.app.services.analysis_markdown.quality import publisher_statistics
from backend.app.services.analysis_markdown.replacement_finder import (
    find_replacement,
    related_query_variants,
    search_related_candidates,
)
from backend.app.services.analysis_markdown.service import _prepare
from backend.app.services.extraction.cleaner import clean_article_text
from backend.app.services.extraction.evidence_quality import assess
from backend.app.services.extraction.evidence_validation import body_errors, validate_source


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
    "cleaning_rule_version": "article-clean-v2.3",
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


def test_cleaner_removes_requested_page_ui_photo_labels_and_resale_tail():
    facts = (
        "한국전기안전공사는 여름철 전기설비 특별점검을 시작했다.\n"
        "점검 결과와 후속 조치는 다음 달 공개할 예정이다."
    )
    page_extras = "\n".join([
        "기사 스크랩", "댓글", "공유", "글자크기 조절", "프린트", "상태바",
        "구독", "구독중", "이미지 확대", "사진=연합뉴스", "[사진=한국전기안전공사]",
        "재판매 및 DB 금지",
    ])

    result = clean_article_text(f"{facts}\n{page_extras}")

    assert result.text == facts.replace("\n", "\n\n")
    assert result.noise_detected is True
    assert "page_ui" in result.removed_sections
    assert "photo_caption" in result.removed_sections
    assert "copyright_tail" in result.removed_sections


def test_cleaner_does_not_remove_ui_words_inside_article_sentences():
    text = "독자들은 기사를 공유하고 구독 중이라고 밝혔으며 사진 활용 정책도 설명했다."
    assert clean_article_text(text).text == text


def test_eligibility_rejects_navigation_and_short_text_but_accepts_factual_rss():
    navigation = clean_article_text(("많이 본 뉴스 로그인 메뉴 기사목록 좋아요 응원해요 " * 20))
    assert evaluate(navigation, status="success_full", url="https://kbs.co.kr/a", config=CONFIG).reason == "navigation_only"
    short = clean_article_text("짧은 기사")
    assert evaluate(short, status="success_full", url="https://example.com/a", config=CONFIG).reason == "body_too_short"
    summary = clean_article_text("7월 20일 정부는 전기요금 시간 차등제를 검토한다고 밝혔으며 구체적 적용 대상과 시범사업 계획, 향후 일정과 소비자 영향 등을 관계기관과 논의하고 있다고 설명했다. " * 2)
    assert evaluate(summary, status="success_summary", url="https://news1.kr/a", config=CONFIG).eligible


def test_prepare_uses_eligible_official_rss_when_stored_page_body_is_contaminated():
    article = {
        "id": "government-release-1",
        "title": "정부 전기안전 대책 공식 발표",
        "source": "정부부처 보도자료",
        "rawSource": "정책브리핑",
        "url": "https://www.korea.kr/news/policyNewsView.do?newsId=1",
        "pubDate": "2026-07-23T01:00:00Z",
        "bodyText": "많이 본 뉴스 로그인 메뉴 기사목록 좋아요 응원해요 " * 30,
        "description": (
            "정부는 전기설비 40곳의 안전점검 결과와 피해 수치, 후속 조사 일정 및 "
            "재발 방지 대책을 관계기관과 함께 확인해 발표했다고 밝혔다. " * 4
        ),
    }

    prepared = _prepare(article, CONFIG, allow_network=False)

    assert prepared["analysisEligible"] is True
    assert prepared["status"] == "success_summary"
    assert prepared["extractionMethod"] == "official_rss"
    assert prepared["rawText"] == article["description"]


def test_clean_full_text_remains_eligible_after_page_extras_are_removed():
    text = "정부는 전력계통 기술기준 개편 방향과 후속 일정을 발표했다. " * 15
    cleaning = clean_article_text(text + " 추천기사 많이 본 뉴스")
    result = assess(
        {
            "source": "한국경제",
            "pubDate": "2026-07-20T12:01:00Z",
            "url": "https://hankyung.com/example",
            "rawText": text,
        },
        cleaning,
        status="success_full",
        method="original",
        config=CONFIG,
    )
    assert cleaning.noise_detected is True
    assert result["analysisEligible"] is True
    assert "페이지 부가 콘텐츠 제거" in result["qualityReasons"]


def test_article_facts_remain_eligible_after_publisher_ai_section_is_removed():
    facts = "소방당국은 화재 조사 결과와 피해 수치, 후속 점검 계획을 발표했다. " * 15
    cleaning = clean_article_text(
        facts + " 핵심요약 쏙 AI 요약입니다. AI 해설 Key Points 시나리오별 전망"
    )
    result = assess(
        {
            "source": "매일경제",
            "pubDate": "2026-07-20T12:01:00Z",
            "url": "https://mk.co.kr/example",
            "rawText": facts,
        },
        cleaning,
        status="success_full",
        method="stored_body",
        config=CONFIG,
    )
    assert cleaning.ai_content_detected is True
    assert result["analysisEligible"] is True
    assert "언론사 AI 콘텐츠 감지" in result["qualityReasons"]


def test_long_article_with_trailing_page_fragment_is_absolute_error():
    text = (
        "기상청은 집중호우 피해 현황과 대피 인원, 후속 안전조치 계획을 발표했다. " * 12
    ) + "인기 키워드 취재플러스"
    result = assess(
        {
            "source": "MBC",
            "pubDate": "2026-07-20T12:01:00Z",
            "url": "https://imnews.imbc.com/example",
            "rawText": text,
        },
        clean_article_text(text),
        status="success_full",
        method="stored_body",
        config=CONFIG,
    )
    assert result["completeSentenceCount"] >= 2
    assert "문장 종료 불완전" in result["qualityReasons"]
    assert result["analysisEligible"] is False
    assert result["qualityGrade"] == "unavailable"
    assert "body_truncated" in result["validationErrors"]


def test_truncated_body_patterns_override_a_high_quality_score():
    base = "관계기관은 전기설비 안전점검 결과와 후속 계획을 발표했다. " * 15
    for ending in ["다만 가정 돌봄이...", "후속 대책은 관계기관과 협의", '관계자는 “추가 조사 중이라고 말했다.']:
        result = assess(
            {"source": "KBS", "pubDate": "2026-07-20T12:01:00Z", "url": "https://news.kbs.co.kr/a", "rawText": base + ending},
            clean_article_text(base + ending), status="success_full", method="stored_body", config=CONFIG,
        )
        assert result["analysisEligible"] is False
        assert "body_truncated" in result["validationErrors"]
        assert result["contentQualityScore"] <= 59


def test_contamination_removed_cleanly_passes_but_residual_contamination_fails():
    facts = "소방당국은 화재 피해와 조사 일정, 후속 안전조치 계획을 발표했다. " * 12
    assert body_errors(clean_article_text(facts + " 추천기사 다른 사건 기사").text, status="success_full") == ()
    residual = clean_article_text(facts + " 많이 본 기사 1. 다른 사건이 발생했다.")
    assert "body_contaminated" in body_errors(residual.text, status="success_full")
    hani_residual = facts + " Your browser does not support the audio element. 뉴스룸 PICK"
    assert "body_contaminated" in body_errors(hani_residual, status="success_full")


def test_source_normalization_and_publisher_conflict_use_page_and_url_evidence():
    normalized = validate_source(
        raw_source="KBS", displayed_source="KBS", source_url="https://joongang.co.kr/a",
        resolved_url="https://joongang.co.kr/a", canonical_url="https://www.joongang.co.kr/a",
        page_publisher="중앙일보",
    )
    assert normalized.source == "중앙일보"
    assert normalized.raw_source == "KBS"
    assert normalized.errors == ()
    assert normalized.normalization_reason == "resolved_domain_and_page_publisher"

    mismatch = validate_source(
        raw_source="KBS", displayed_source="KBS", source_url="https://joongang.co.kr/a",
        resolved_url="https://joongang.co.kr/a", canonical_url="https://joongang.co.kr/a",
        page_publisher="KBS",
    )
    assert "publisher_identity_mismatch" in mismatch.errors

    canonical_conflict = validate_source(
        raw_source="KBS", displayed_source="KBS", source_url="https://news.kbs.co.kr/a",
        resolved_url="https://news.kbs.co.kr/a", canonical_url="https://joongang.co.kr/a",
    )
    assert "publisher_identity_mismatch" in canonical_conflict.errors

    google_unresolved = validate_source(
        raw_source="중앙일보", displayed_source="중앙일보",
        source_url="https://news.google.com/rss/articles/token",
    )
    assert "canonical_url_unresolved" in google_unresolved.errors


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


def test_related_search_relaxes_topic_and_trusted_media_policy_but_requires_domain(monkeypatch):
    queries = []
    items = [
        {
            "title": f"변전소 침수 안전점검 후속 대책 {index}",
            "url": f"https://news.google.com/articles/{index}",
            "sourceUrl": "https://www.yna.co.kr",
            "source": "연합뉴스",
            "provider": "Google 뉴스 RSS",
            "pubDate": f"2026-07-{20 - index % 10:02d}T01:00:00Z",
            "description": "후속 보도",
        }
        for index in range(12)
    ]
    items.append({
        "title": "전주 변전소 침수 대비 안전점검 결과 후속",
        "url": "https://news.google.com/articles/untrusted",
        "sourceUrl": "https://untrusted.example.com",
        "source": "미등록매체",
        "provider": "Google 뉴스 RSS",
        "pubDate": "2026-07-21T01:00:00Z",
    })
    items.append({
        "title": "변전소 침수 안전점검 후속 대책 출처미상",
        "url": "https://news.google.com/articles/unknown",
        "source": "출처 미상",
        "provider": "Google 뉴스 RSS",
        "pubDate": "2026-07-21T02:00:00Z",
    })
    def fake_google(query, lookback, maximum):
        queries.append(query)
        return items

    monkeypatch.setattr(
        "backend.app.services.analysis_markdown.replacement_finder.fetch_google_rss",
        fake_google,
    )

    found = search_related_candidates(
        {"title": "전주 변전소 침수 대비 안전점검 결과 발표", "url": "https://original.example.com"}
    )

    assert len(found) == 10
    assert any(item["source"] == "미등록매체" for item in found)
    assert all(item["source"] != "출처 미상" for item in found)
    assert any(item["relatedSearchPublisherScope"] == "domain_identified" for item in found)
    assert all(item["relatedSearchPolicy"] == "relaxed_topic_filters_v1" for item in found)
    assert len(queries) >= 4
    assert all(len(query.split()) <= 3 for query in queries)


def test_related_query_variants_cover_front_back_and_short_combinations():
    variants = related_query_variants({
        "title": "인천 물류센터 리튬배터리 화재 합동감식 원인 조사 착수"
    })

    assert "인천 물류센터 리튬배터리" in variants
    assert "원인 조사 착수" in variants
    assert "인천 물류센터" in variants
    assert len(variants) == len(set(variants))


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
            "INSERT INTO publisher_extraction_events VALUES (?, 'a', 'bad', '나쁜언론', 'failed', 0, 0, 0, 1, 'access_blocked', ?, 'article-clean-v2.3')",
            (str(index), f"2026-07-{index + 1:02d}"),
        )
    connection.execute("INSERT INTO publisher_extraction_events VALUES ('x', 'a', 'new', '신규언론', 'success_full', 1, 0, 0, 0, NULL, '2026-07-20', 'article-clean-v2.3')")
    stats = {item["publisherId"]: item for item in publisher_statistics(connection, CONFIG)}
    assert stats["bad"]["status"] == "quarantine"
    assert stats["new"]["status"] == "warning"
