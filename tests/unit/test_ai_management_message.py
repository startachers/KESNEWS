from backend.app.services.ai.analyzer import format_analysis
from backend.app.services.ai.prompt_builder import PROMPT_VERSION, build_prompt


def test_format_analysis_uses_three_management_message_sections():
    result = {
        "managementMessage": {"text": "현장 실행력을 우선 살펴볼 필요가 있습니다."},
        "situationSummary": {"text": "폭염과 전력사용 증가에 대비한 예방활동을 점검합니다."},
        "keyIssues": [
            {
                "title": "여름철 안전",
                "urgency": "required",
                "summary": "핵심 현안",
                "managementImpact": "현장점검 필요",
            },
            {
                "title": "정보보안",
                "urgency": "reference",
                "summary": "공공시스템 취약점 점검이 확대되고 있습니다.",
                "managementImpact": "공사의 대응체계를 살펴볼 수 있겠습니다.",
            },
        ],
    }

    assert format_analysis(result) == (
        "① 오늘의 핵심\n"
        "현장 실행력을 우선 살펴볼 필요가 있습니다.\n\n"
        "② 경영 시사점\n"
        "폭염과 전력사용 증가에 대비한 예방활동을 점검합니다.\n\n"
        "③ 참고 동향\n"
        "공공시스템 취약점 점검이 확대되고 있습니다. 공사의 대응체계를 살펴볼 수 있겠습니다."
    )


def test_format_analysis_does_not_invent_reference_trend():
    result = {
        "managementMessage": {"text": "오늘의 핵심"},
        "situationSummary": {"text": "경영 시사점"},
        "keyIssues": [{"urgency": "review", "summary": "검토", "managementImpact": "영향"}],
    }

    assert format_analysis(result).endswith("③ 참고 동향\n별도 참고 동향 없음.")


def test_prompt_requests_the_management_message_direction_and_no_duplicate_headings():
    prompt = build_prompt("2026-07-17", "홍보실", [])

    assert PROMPT_VERSION == "phase7-management-message-v2"
    assert "① 오늘의 핵심 — managementMessage.text" in prompt
    assert "② 경영 시사점 — situationSummary.text" in prompt
    assert "③ 참고 동향 — keyIssues 중 urgency가 reference인 항목" in prompt
    assert "각 필드의 `text`에는 제목이나 번호를 넣지 말고" in prompt
    assert "현장 실행력, 국민 체감형 안전안내" in prompt
