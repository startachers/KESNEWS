from backend.app.services.ai.grounding import validate_basis_items, validate_final_result
from backend.app.services.ai.jurisdiction import load_jurisdiction_policy
from backend.app.services.ai.schemas import AnalysisBasisItem, AnalysisResult


def article(article_id: str, title: str, content: str) -> dict:
    return {
        "id": article_id,
        "title": title,
        "source": "회귀테스트일보",
        "publishedAt": "2026-07-21T08:00:00+09:00",
        "content": content,
        "editorNote": "",
    }


def basis(
    *,
    article_id: str = "A01",
    fact: str,
    interpretation: str,
    recommendation: str,
    certainty: str,
    electrical: str,
    jurisdiction: str,
    action_level: str,
    owner: str,
    excluded: list[str] | None = None,
) -> AnalysisBasisItem:
    return AnalysisBasisItem.model_validate(
        {
            "section": "core",
            "articleFact": fact,
            "attributedClaim": "",
            "kescoInterpretation": interpretation,
            "managementRecommendation": recommendation,
            "articleIds": [article_id],
            "evidenceQuotes": [{"articleId": article_id, "fact": fact}],
            "certainty": certainty,
            "electricalCauseStatus": electrical,
            "kescoJurisdiction": jurisdiction,
            "jurisdictionReason": interpretation or "공사 소관이 아님",
            "excludedElements": excluded or [],
            "actionLevel": action_level,
            "ownerType": owner,
        }
    )


def final_result(*, key_issue: dict, action_items: list[dict]) -> AnalysisResult:
    return AnalysisResult.model_validate(
        {
            "managementMessage": {"text": "공식 조사 결과를 확인할 필요가 있다.", "articleIds": ["A01"]},
            "situationSummary": {"text": "현재 보도만으로 원인을 판단하기 어렵다.", "articleIds": ["A01"]},
            "keyIssues": [key_issue],
            "decisionPoints": [],
            "actionItems": action_items,
            "riskOutlook": {"text": "후속 조사 결과에 따라 검토할 수 있다.", "articleIds": ["A01"], "isInference": True},
            "limitations": [],
            "confidence": "medium",
        }
    )


def test_policy_file_is_loaded_by_analysis_service():
    policy = load_jurisdiction_policy()
    assert policy["version"] == "2026-07-21-v1"
    assert "메자닌 구조" in policy["out_of_scope"]
    assert "그리드코드" in policy["monitoring"]


def test_a01_rejects_mezzanine_inspection_recommendation_without_electrical_cause():
    evidence = [article("A01", "쿠팡 물류센터 화재", "메자닌 구조와 가연물로 진화가 장기화됐다. 화재 원인은 조사 중이다.")]
    invalid = basis(
        fact="메자닌 구조와 가연물로 진화가 장기화됐다.",
        interpretation="공사가 특수 물류시설을 점검해야 한다.",
        recommendation="메자닌 구조 등 특수 물류시설의 점검 항목을 세분화한다.",
        certainty="reported",
        electrical="not_confirmed",
        jurisdiction="DIRECT",
        action_level="internal_review",
        owner="KESCO",
        excluded=["가연물 적재"],
    )

    accepted, warnings = validate_basis_items([invalid], evidence)

    assert accepted == []
    assert {warning["code"] for warning in warnings} >= {
        "OUT_OF_SCOPE_RECOMMENDATION",
        "UNCONFIRMED_ELECTRICAL_ACTION",
    }


def test_a01_allows_conditional_interagency_follow_up():
    evidence = [article("A01", "쿠팡 물류센터 화재", "메자닌 구조와 가연물로 진화가 장기화됐다. 화재 원인은 조사 중이다.")]
    allowed = basis(
        fact="화재 원인은 조사 중이다.",
        interpretation="공식 조사에서 전기적 요인이 확인되는지 관계기관과 확인할 사안이다.",
        recommendation="공식 조사 결과에서 전기적 요인이 확인되는 경우에 한해 관련 기준 보완 필요성을 검토할 수 있다.",
        certainty="unknown",
        electrical="not_confirmed",
        jurisdiction="COLLABORATIVE",
        action_level="interagency_coordination",
        owner="KESCO_WITH_PARTNERS",
        excluded=["메자닌 구조", "가연물 적재"],
    )

    accepted, warnings = validate_basis_items([allowed], evidence)

    assert accepted == [allowed]
    assert warnings == []


def test_a06_blocks_invented_detector_failure_and_cause_overstatement():
    evidence = [article("A01", "은마아파트 화재", "공식 결론은 원인 미상이다. 전기적 원인으로 추정되며 무자격 배선공사의 영향 가능성이 제기됐다.")]
    invented = basis(
        fact="감지기가 작동하지 않아 화재가 발생했다.",
        interpretation="전기화재로 확인됐다.",
        recommendation="단속을 강화한다.",
        certainty="unknown",
        electrical="suspected",
        jurisdiction="COLLABORATIVE",
        action_level="interagency_coordination",
        owner="KESCO_WITH_PARTNERS",
    )

    accepted, warnings = validate_basis_items([invented], evidence)

    assert accepted == []
    codes = {warning["code"] for warning in warnings}
    assert "UNSUPPORTED_CONCEPT" in codes
    assert "INVESTIGATION_OVERSTATED" in codes or "UNCERTAINTY_OVERSTATED" in codes


def test_grid_code_is_not_accepted_as_direct_kesco_action():
    evidence = [article("A01", "그리드코드 개편", "정부가 그리드코드 개편 방향을 발표했다.")]
    invalid = basis(
        fact="정부가 그리드코드 개편 방향을 발표했다.",
        interpretation="공사가 그리드코드를 현행 업무에 반영한다.",
        recommendation="그리드코드를 검사 업무에 즉시 반영한다.",
        certainty="reported",
        electrical="not_applicable",
        jurisdiction="DIRECT",
        action_level="internal_review",
        owner="KESCO",
    )

    accepted, warnings = validate_basis_items([invalid], evidence)

    assert accepted == []
    assert "MONITORING_AS_DIRECT" in {warning["code"] for warning in warnings}


def test_bess_capability_review_is_allowed_without_inventing_current_role():
    evidence = [article("A01", "해남 BESS 구축", "해남에 대규모 BESS 구축 계획이 발표됐다.")]
    allowed = basis(
        fact="해남에 대규모 BESS 구축 계획이 발표됐다.",
        interpretation="신규 전기설비 확산이 검사·진단 역량에 미칠 영향을 살펴볼 사안이다.",
        recommendation="전문인력·장비·교육 준비 수준을 검토할 필요가 있다.",
        certainty="reported",
        electrical="not_applicable",
        jurisdiction="DIRECT",
        action_level="internal_review",
        owner="KESCO",
    )

    accepted, warnings = validate_basis_items([allowed], evidence)

    assert accepted == [allowed]
    assert warnings == []


def test_final_result_rejects_external_action_and_absent_smr():
    evidence = [article("A01", "AI 윤리 원칙", "정부가 공공부문 AI 윤리 원칙을 발표했다.")]
    basis_item = basis(
        fact="정부가 공공부문 AI 윤리 원칙을 발표했다.",
        interpretation="주무부처 정책 동향을 살펴볼 사안이다.",
        recommendation="공사 도입 현황을 확인한 뒤 적용 여부를 검토한다.",
        certainty="reported",
        electrical="not_applicable",
        jurisdiction="MONITORING",
        action_level="policy_monitoring",
        owner="UNDETERMINED",
    )
    issue = {
        "title": "AI 윤리 원칙",
        "urgency": "reference",
        "summary": "정부가 공공부문 AI 윤리 원칙을 발표했다.",
        "managementImpact": "SMR 사업과 공사 내 도입 중인 AI 서비스에 즉시 반영한다.",
        "articleIds": ["A01"],
        "evidenceQuotes": [{"articleId": "A01", "fact": "정부가 공공부문 AI 윤리 원칙을 발표했다."}],
        "certainty": "reported",
        "electricalCauseStatus": "not_applicable",
        "kescoJurisdiction": "MONITORING",
        "jurisdictionReason": "주무부처 정책 동향",
        "excludedElements": [],
        "recommendation": "적용 동향을 모니터링한다.",
        "actionLevel": "policy_monitoring",
    }
    action = {
        "priority": "review",
        "action": "외부기관에 AI 서비스 적용을 지시한다.",
        "articleIds": ["A01"],
        "kescoJurisdiction": "COLLABORATIVE",
        "actionLevel": "interagency_coordination",
        "evidence": "정부 AI 윤리 원칙",
        "uncertainty": "reported",
        "ownerType": "EXTERNAL_AGENCY",
    }

    warnings = validate_final_result(
        final_result(key_issue=issue, action_items=[action]), evidence, [basis_item]
    )

    codes = {warning["code"] for warning in warnings}
    assert "UNSUPPORTED_CONCEPT" in codes
    assert "EXTERNAL_ACTION_AS_KESCO" in codes
