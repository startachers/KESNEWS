from backend.app.services.ai.analyzer import format_analysis
from backend.app.services.ai.prompt_builder import PROMPT_VERSION, build_basis_prompt, build_prompt


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
                "kescoJurisdiction": "MONITORING",
            },
        ],
        "actionItems": [{"action": "현장 예방활동을 점검합니다.", "kescoJurisdiction": "DIRECT", "ownerType": "KESCO"}],
    }

    assert format_analysis(result) == (
        "① 오늘 한줄\n"
        "현장 실행력을 우선 살펴볼 필요가 있습니다.\n\n"
        "② 언론 동향 분석\n"
        "폭염과 전력사용 증가에 대비한 예방활동을 점검합니다.\n\n"
        "③ 경영 참고사항\n"
        "현장 예방활동을 점검합니다.\n\n"
        "④ 기타 동향\n"
        "공공시스템 취약점 점검이 확대되고 있습니다. 공사의 대응체계를 살펴볼 수 있겠습니다."
    )


def test_format_analysis_does_not_invent_reference_trend():
    result = {
        "managementMessage": {"text": "오늘의 핵심"},
        "situationSummary": {"text": "경영 시사점"},
        "keyIssues": [{"urgency": "review", "summary": "검토", "managementImpact": "영향"}],
    }

    assert format_analysis(result).endswith("③ 경영 참고사항\n직접적인 경영 현안은 제한적입니다.")


def test_prompt_requests_the_management_message_direction_and_no_duplicate_headings():
    prompt = build_prompt("2026-07-17", "홍보실", [])

    assert PROMPT_VERSION == "kesco-jurisdiction-grounding-v1"
    assert "① 오늘 한줄 — managementMessage.text" in prompt
    assert "② 언론 동향 분석 — situationSummary.text" in prompt
    assert "③ 경영 참고사항 — actionItems" in prompt
    assert "각 필드의 `text`에는 제목이나 번호를 넣지 말고" in prompt
    assert "현장 실행력, 국민 체감형 안전안내" in prompt
    assert "단기 현안 → 중장기 과제" in prompt
    assert "기사에서 확인된 사실 → 공사 관점 해석 → 확인 또는 검토사항" in prompt
    assert "기사 1은 …, 기사 2는 …" in prompt
    assert "위 소재를 매일 의무적으로 채우지 않는다" in prompt
    assert "한국전기안전공사를 송전망 건설, 전력 공급" in prompt

    basis_prompt = build_basis_prompt("2026-07-17", "홍보실", [])
    assert "articleFact: 기사에서 확인된 사실만" in basis_prompt
    assert "attributedClaim: 언론·전문가의 주장만 출처를 표시" in basis_prompt
    assert "certainty: confirmed, reported, suspected, unknown" in basis_prompt
    assert "KESCO 업무 소관 정책" in basis_prompt
