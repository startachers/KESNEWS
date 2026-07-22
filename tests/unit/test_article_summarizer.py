from backend.app.services.ai.article_summarizer import (
    MAX_SUMMARY_CHARACTERS,
    _compact_summary,
    _repeats_title,
)


def test_compact_summary_limits_lines_and_characters():
    summary = _compact_summary(
        "첫째 줄 핵심 사실입니다.\n"
        "둘째 줄 핵심 수치입니다.\n"
        "셋째 줄 영향입니다.\n"
        + "네 번째 줄은 제외되어야 합니다. " * 20
    )

    assert "\n" not in summary
    assert "네 번째 줄" not in summary
    assert len(summary) <= MAX_SUMMARY_CHARACTERS


def test_repeats_title_detects_rephrased_headline_but_allows_new_detail():
    title = "압구정 아파트 화재…주민 20여 명 대피"

    assert _repeats_title(
        title, "압구정 아파트에서 화재가 발생해 주민 20여 명이 대피했습니다."
    )
    assert not _repeats_title(
        title, "소방당국은 로봇청소기 발화 가능성을 포함해 정확한 원인을 조사 중입니다."
    )
