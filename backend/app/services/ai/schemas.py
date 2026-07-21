from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Claim(_StrictModel):
    text: str
    articleIds: list[str] = Field(default_factory=list)


Certainty = Literal["confirmed", "reported", "suspected", "unknown"]
ElectricalCauseStatus = Literal["confirmed", "suspected", "not_confirmed", "not_applicable"]
KescoJurisdiction = Literal["DIRECT", "COLLABORATIVE", "MONITORING", "OUT_OF_SCOPE"]
ActionLevel = Literal[
    "internal_review", "interagency_coordination", "policy_monitoring", "exclude"
]
OwnerType = Literal["KESCO", "KESCO_WITH_PARTNERS", "EXTERNAL_AGENCY", "UNDETERMINED"]


class EvidenceQuote(_StrictModel):
    articleId: str
    fact: str = Field(min_length=1)


class KeyIssue(_StrictModel):
    title: str
    urgency: Literal["required", "review", "reference"]
    summary: str
    managementImpact: str
    articleIds: list[str] = Field(default_factory=list)
    evidenceQuotes: list[EvidenceQuote] = Field(min_length=1)
    certainty: Certainty
    electricalCauseStatus: ElectricalCauseStatus
    kescoJurisdiction: KescoJurisdiction
    jurisdictionReason: str = Field(min_length=1)
    excludedElements: list[str] = Field(default_factory=list)
    recommendation: str
    actionLevel: ActionLevel

    @model_validator(mode="after")
    def enforce_scope(self) -> "KeyIssue":
        if self.kescoJurisdiction == "OUT_OF_SCOPE":
            if self.recommendation.strip():
                raise ValueError("OUT_OF_SCOPE 이슈에는 recommendation을 둘 수 없습니다.")
            if self.actionLevel != "exclude":
                raise ValueError("OUT_OF_SCOPE 이슈의 actionLevel은 exclude여야 합니다.")
        return self


class ActionItem(_StrictModel):
    priority: Literal["required", "review", "reference"]
    action: str
    articleIds: list[str] = Field(default_factory=list)
    kescoJurisdiction: KescoJurisdiction
    actionLevel: ActionLevel
    evidence: str = Field(min_length=1)
    uncertainty: Certainty
    ownerType: OwnerType

    @model_validator(mode="after")
    def exclude_out_of_scope_action(self) -> "ActionItem":
        if self.kescoJurisdiction == "OUT_OF_SCOPE":
            raise ValueError("OUT_OF_SCOPE 조치는 최종 actionItems에 포함할 수 없습니다.")
        return self


class RiskOutlook(Claim):
    isInference: Literal[True]


class WeatherClaim(_StrictModel):
    text: str = ""
    weatherSignalIds: list[str] = Field(default_factory=list)


class AnalysisBasisItem(_StrictModel):
    section: Literal["core", "implication", "reference"]
    articleFact: str
    attributedClaim: str
    kescoInterpretation: str
    managementRecommendation: str
    articleIds: list[str] = Field(min_length=1)
    evidenceQuotes: list[EvidenceQuote] = Field(min_length=1)
    certainty: Certainty
    electricalCauseStatus: ElectricalCauseStatus
    kescoJurisdiction: KescoJurisdiction
    jurisdictionReason: str = Field(min_length=1)
    excludedElements: list[str] = Field(default_factory=list)
    actionLevel: ActionLevel
    ownerType: OwnerType

    @model_validator(mode="after")
    def require_content(self) -> "AnalysisBasisItem":
        if not any(
            value.strip()
            for value in (
                self.articleFact,
                self.attributedClaim,
                self.kescoInterpretation,
                self.managementRecommendation,
            )
        ):
            raise ValueError("분석 근거 항목의 내용이 모두 비어 있습니다.")
        if self.kescoJurisdiction == "OUT_OF_SCOPE":
            if self.managementRecommendation.strip():
                raise ValueError("OUT_OF_SCOPE 근거에는 경영 제언을 둘 수 없습니다.")
            if self.actionLevel != "exclude":
                raise ValueError("OUT_OF_SCOPE 근거의 actionLevel은 exclude여야 합니다.")
        return self


class AnalysisBasis(_StrictModel):
    items: list[AnalysisBasisItem] = Field(min_length=1)
    limitations: list[Claim] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"]


class AnalysisResult(_StrictModel):
    managementMessage: Claim
    situationSummary: Claim
    keyIssues: list[KeyIssue] = Field(default_factory=list)
    decisionPoints: list[Claim] = Field(default_factory=list)
    actionItems: list[ActionItem] = Field(default_factory=list)
    riskOutlook: RiskOutlook
    limitations: list[Claim] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"]
    weatherManagementMessage: WeatherClaim = Field(default_factory=WeatherClaim)

    @model_validator(mode="after")
    def require_claim_evidence(self) -> "AnalysisResult":
        claims: list[tuple[str, str, list[str]]] = [
            ("managementMessage", self.managementMessage.text, self.managementMessage.articleIds),
            ("situationSummary", self.situationSummary.text, self.situationSummary.articleIds),
            ("riskOutlook", self.riskOutlook.text, self.riskOutlook.articleIds),
        ]
        claims.extend(
            (f"keyIssues[{index}]", " ".join((item.title, item.summary, item.managementImpact)), item.articleIds)
            for index, item in enumerate(self.keyIssues)
        )
        claims.extend(
            (f"decisionPoints[{index}]", item.text, item.articleIds)
            for index, item in enumerate(self.decisionPoints)
        )
        claims.extend(
            (f"actionItems[{index}]", item.action, item.articleIds)
            for index, item in enumerate(self.actionItems)
        )
        missing = [name for name, text, ids in claims if text.strip() and not ids]
        if missing:
            raise ValueError(f"내용이 있는 주장에 articleIds가 없습니다: {', '.join(missing)}")
        return self


def validate_evidence(result: AnalysisResult, evidence_ids: set[str]) -> None:
    references: list[tuple[str, list[str]]] = [
        ("managementMessage", result.managementMessage.articleIds),
        ("situationSummary", result.situationSummary.articleIds),
        ("riskOutlook", result.riskOutlook.articleIds),
    ]
    references.extend((f"keyIssues[{i}]", item.articleIds) for i, item in enumerate(result.keyIssues))
    references.extend(
        (f"decisionPoints[{i}]", item.articleIds) for i, item in enumerate(result.decisionPoints)
    )
    references.extend((f"actionItems[{i}]", item.articleIds) for i, item in enumerate(result.actionItems))
    references.extend(
        (f"keyIssues[{i}].evidenceQuotes", [quote.articleId for quote in item.evidenceQuotes])
        for i, item in enumerate(result.keyIssues)
    )
    references.extend((f"limitations[{i}]", item.articleIds) for i, item in enumerate(result.limitations))
    invalid = sorted({value for _, ids in references for value in ids if value not in evidence_ids})
    if invalid:
        raise ValueError(f"입력 evidence index에 없는 ID입니다: {', '.join(invalid)}")


def validate_basis_evidence(result: AnalysisBasis, evidence_ids: set[str]) -> None:
    references = [item.articleIds for item in result.items]
    references.extend(item.articleIds for item in result.limitations)
    references.extend([quote.articleId for quote in item.evidenceQuotes] for item in result.items)
    invalid = sorted({value for ids in references for value in ids if value not in evidence_ids})
    if invalid:
        raise ValueError(f"입력 evidence index에 없는 ID입니다: {', '.join(invalid)}")
