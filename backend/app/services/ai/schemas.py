from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Claim(_StrictModel):
    text: str
    articleIds: list[str] = Field(default_factory=list)


class KeyIssue(_StrictModel):
    title: str
    urgency: Literal["required", "review", "reference"]
    summary: str
    managementImpact: str
    articleIds: list[str] = Field(default_factory=list)


class ActionItem(_StrictModel):
    priority: Literal["required", "review", "reference"]
    action: str
    articleIds: list[str] = Field(default_factory=list)


class RiskOutlook(Claim):
    isInference: Literal[True]


class AnalysisBasisItem(_StrictModel):
    section: Literal["core", "implication", "reference"]
    articleFact: str
    attributedClaim: str
    kescoInterpretation: str
    managementRecommendation: str
    articleIds: list[str] = Field(min_length=1)
    certainty: Literal["confirmed", "attributed", "under_investigation", "inference"]

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
    references.extend((f"limitations[{i}]", item.articleIds) for i, item in enumerate(result.limitations))
    invalid = sorted({value for _, ids in references for value in ids if value not in evidence_ids})
    if invalid:
        raise ValueError(f"입력 evidence index에 없는 ID입니다: {', '.join(invalid)}")


def validate_basis_evidence(result: AnalysisBasis, evidence_ids: set[str]) -> None:
    references = [item.articleIds for item in result.items]
    references.extend(item.articleIds for item in result.limitations)
    invalid = sorted({value for ids in references for value in ids if value not in evidence_ids})
    if invalid:
        raise ValueError(f"입력 evidence index에 없는 ID입니다: {', '.join(invalid)}")
