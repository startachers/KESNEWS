from backend.app.services.ai.grounding import validate_basis_items
from backend.app.services.ai.schemas import AnalysisBasisItem


def article_input(content: str) -> list[dict]:
    return [
        {
            "id": "A01",
            "title": "전기설비 화재 조사",
            "source": "테스트일보",
            "publishedAt": "2026-07-17T08:00:00+09:00",
            "content": content,
        }
    ]


def basis_item(**changes) -> AnalysisBasisItem:
    payload = {
        "section": "core",
        "articleFact": "소방 당국은 화재 원인을 조사 중이라고 밝혔다.",
        "attributedClaim": "전문가는 제도 공백 가능성을 지적했다.",
        "kescoInterpretation": "공사의 현행 검사 업무 범위를 살펴볼 사안이다.",
        "managementRecommendation": "관련 설비의 점검 현황과 안내자료를 확인할 필요가 있다.",
        "articleIds": ["A01"],
        "certainty": "under_investigation",
    }
    payload.update(changes)
    return AnalysisBasisItem.model_validate(payload)


def test_four_grounding_checks_filter_invalid_basis_items():
    evidence = article_input(
        "소방 당국은 화재 원인을 조사 중이라고 밝혔다. "
        "전문가는 제도 공백 가능성을 지적했다."
    )
    items = [
        basis_item(articleFact="피해액은 300억원으로 확인됐다."),
        basis_item(kescoInterpretation="공사는 송전망 구축을 담당한다."),
        basis_item(articleFact="화재 원인은 배터리 결함이었다."),
        basis_item(attributedClaim="제도 공백 가능성이 있다."),
    ]

    accepted, warnings = validate_basis_items(items, evidence)

    assert accepted == []
    assert {warning["code"] for warning in warnings} == {
        "UNSUPPORTED_NUMBER",
        "KESCO_ROLE_CONFUSION",
        "INVESTIGATION_OVERSTATED",
        "UNATTRIBUTED_CLAIM",
    }


def test_reference_item_requires_internal_management_evidence():
    outside = basis_item(section="reference", attributedClaim="")
    accepted, warnings = validate_basis_items(
        [outside], article_input("전기설비 안전점검을 실시했다.")
    )
    assert accepted == []
    assert warnings[0]["code"] == "REFERENCE_SCOPE_INVALID"

    inside = basis_item(
        section="reference",
        articleFact="공공기관 정보보안 계약 점검이 진행됐다.",
        attributedClaim="",
        certainty="confirmed",
    )
    accepted, warnings = validate_basis_items(
        [inside], article_input("공공기관 정보보안 계약 점검이 진행됐다.")
    )
    assert accepted == [inside]
    assert warnings == []
