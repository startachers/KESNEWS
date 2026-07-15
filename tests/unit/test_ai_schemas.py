import pytest
from pydantic import ValidationError

from backend.app.services.ai.schemas import AnalysisResult, validate_evidence
from backend.app.services.ai.analyzer import input_signature


def valid_analysis() -> dict:
    return {
        "managementMessage": {"text": "경영 메시지", "articleIds": ["A01"]},
        "situationSummary": {"text": "상황 요약", "articleIds": ["A01"]},
        "keyIssues": [
            {
                "title": "이슈",
                "urgency": "required",
                "summary": "요약",
                "managementImpact": "영향",
                "articleIds": ["A01"],
            }
        ],
        "decisionPoints": [{"text": "판단", "articleIds": ["A01"]}],
        "actionItems": [
            {"priority": "review", "action": "확인", "articleIds": ["A01"]}
        ],
        "riskOutlook": {"text": "전망", "articleIds": ["A01"], "isInference": True},
        "limitations": [{"text": "본문 미확보", "articleIds": []}],
        "confidence": "medium",
    }


@pytest.mark.parametrize(
    ("field", "mutate"),
    [
        ("managementMessage", lambda data: data["managementMessage"].update(articleIds=[])),
        ("situationSummary", lambda data: data["situationSummary"].update(articleIds=[])),
        ("keyIssues", lambda data: data["keyIssues"][0].update(articleIds=[])),
        ("decisionPoints", lambda data: data["decisionPoints"][0].update(articleIds=[])),
        ("actionItems", lambda data: data["actionItems"][0].update(articleIds=[])),
        ("riskOutlook", lambda data: data["riskOutlook"].update(articleIds=[])),
    ],
)
def test_every_nonempty_claim_requires_evidence(field, mutate):
    payload = valid_analysis()
    mutate(payload)
    with pytest.raises(ValidationError, match=field):
        AnalysisResult.model_validate(payload)


def test_limitations_may_have_empty_evidence_but_unknown_ids_are_rejected():
    result = AnalysisResult.model_validate(valid_analysis())
    validate_evidence(result, {"A01"})
    payload = valid_analysis()
    payload["limitations"][0]["articleIds"] = ["A99"]
    with pytest.raises(ValueError, match="A99"):
        validate_evidence(AnalysisResult.model_validate(payload), {"A01"})


def test_risk_outlook_requires_inference_true():
    payload = valid_analysis()
    payload["riskOutlook"]["isInference"] = False
    with pytest.raises(ValidationError):
        AnalysisResult.model_validate(payload)


def test_input_signature_changes_when_model_changes():
    evidence_input = [{"id": "A01", "title": "기사", "editorNote": ""}]
    assert input_signature("model-a", evidence_input) != input_signature("model-b", evidence_input)
