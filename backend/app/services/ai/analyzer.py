from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import ValidationError

from backend.app.services.ai.grounding import validate_basis_items, validate_final_result
from backend.app.services.ai.prompt_builder import (
    build_basis_prompt,
    build_correction_prompt,
    build_prompt,
)
from backend.app.services.ai.runtime import CancellationToken
from backend.app.services.ai.schemas import (
    AnalysisBasis,
    AnalysisResult,
    validate_basis_evidence,
    validate_evidence,
)
from backend.app.services.weather.ai_context import validated_weather_message


class AiClient(Protocol):
    def generate(
        self,
        *,
        model: str,
        prompt: str,
        format_schema: dict[str, Any] | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> str: ...


class AnalysisError(Exception):
    code = "AI_SCHEMA_INVALID"

    def __init__(
        self,
        message: str,
        *,
        raw_response: str | None = None,
        attempts: int = 0,
        validation_warnings: list[dict[str, Any]] | None = None,
    ):
        super().__init__(message)
        self.raw_response = raw_response
        self.attempts = attempts
        self.validation_warnings = validation_warnings or []


class EvidenceInvalid(AnalysisError):
    code = "AI_EVIDENCE_INVALID"


class GroundingInvalid(AnalysisError):
    code = "AI_GROUNDING_INVALID"


@dataclass(frozen=True)
class AnalysisOutput:
    result: dict[str, Any]
    basis: dict[str, Any]
    validation_warnings: list[dict[str, Any]]
    raw_response: str
    attempts: int
    basis_attempts: int


def select_articles(articles: list[dict[str, Any]], limit: int = 20) -> list[dict[str, Any]]:
    selected = [article for article in articles if article.get("included")]
    selected.sort(
        key=lambda article: (
            article.get("sortOrder") is None,
            article.get("sortOrder") if article.get("sortOrder") is not None else 0,
            -(article.get("relevanceScore") or 0),
            str(article.get("id") or ""),
        )
    )
    return selected[:limit]


def build_evidence_input(
    articles: list[dict[str, Any]], issue_ids_by_article: dict[str, list[str]] | None = None
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    issue_ids_by_article = issue_ids_by_article or {}
    inputs: list[dict[str, Any]] = []
    evidence: dict[str, str] = {}
    for index, article in enumerate(select_articles(articles), start=1):
        evidence_id = f"A{index:02d}"
        article_id = str(article["id"])
        evidence[evidence_id] = article_id
        inputs.append(
            {
                "id": evidence_id,
                "title": article.get("title") or "",
                "source": article.get("source") or "",
                "publishedAt": article.get("pubDate"),
                "content": article.get("bodyText") or article.get("description") or "",
                "bodyStatus": (
                    "full_text"
                    if article.get("bodyText")
                    else "summary_only"
                    if article.get("description")
                    else "missing"
                ),
                "bodyError": article.get("bodyError") or "",
                "editorNote": article.get("note") or "",
                "priority": article.get("priority") or article.get("risk") or "reference",
                "issueIds": issue_ids_by_article.get(article_id, []),
            }
        )
    return inputs, evidence


def input_signature(
    model: str,
    evidence_input: list[dict[str, Any]],
    context_length: int | None = None,
    weather_context: dict[str, Any] | None = None,
) -> str:
    signature_input: dict[str, Any] = {"model": model, "articles": evidence_input}
    if context_length is not None:
        signature_input["contextLength"] = context_length
    if weather_context is not None:
        signature_input["weatherContext"] = weather_context
    raw = json.dumps(
        signature_input,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"phase7-{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"


def _parse_and_validate(raw: str, evidence_ids: set[str]) -> AnalysisResult:
    candidate = raw.strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        candidate = "\n".join(lines[1:-1]) if len(lines) >= 3 else candidate
    try:
        payload = json.loads(candidate)
        result = AnalysisResult.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise AnalysisError(str(exc), raw_response=raw) from exc
    try:
        validate_evidence(result, evidence_ids)
    except ValueError as exc:
        raise EvidenceInvalid(str(exc), raw_response=raw) from exc
    return result


def _parse_basis(raw: str, evidence_ids: set[str]) -> AnalysisBasis:
    candidate = raw.strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        candidate = "\n".join(lines[1:-1]) if len(lines) >= 3 else candidate
    try:
        payload = json.loads(candidate)
        result = AnalysisBasis.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise AnalysisError(str(exc), raw_response=raw) from exc
    try:
        validate_basis_evidence(result, evidence_ids)
    except ValueError as exc:
        raise EvidenceInvalid(str(exc), raw_response=raw) from exc
    return result


def analyze(
    client: AiClient,
    *,
    model: str,
    report_date: str,
    prepared_by: str,
    evidence_input: list[dict[str, Any]],
    evidence: dict[str, str],
    weather_context: dict[str, Any] | None = None,
    weather_fallback: dict[str, Any] | None = None,
    cancel_token: CancellationToken | None = None,
) -> AnalysisOutput:
    basis_prompt = build_basis_prompt(report_date, prepared_by, evidence_input)
    last_error: AnalysisError | None = None
    basis_raw = ""
    for attempt in range(1, 3):
        current_prompt = (
            basis_prompt
            if attempt == 1
            else build_correction_prompt(
                basis_prompt, basis_raw, str(last_error or "중간 분석 schema invalid")
            )
        )
        basis_raw = client.generate(
            model=model,
            prompt=current_prompt,
            format_schema=AnalysisBasis.model_json_schema(),
            cancel_token=cancel_token,
        )
        try:
            basis = _parse_basis(basis_raw, set(evidence))
            basis_attempts = attempt
            break
        except AnalysisError as exc:
            last_error = exc
    else:
        assert last_error is not None
        last_error.attempts = 2
        last_error.raw_response = basis_raw
        raise last_error

    accepted, validation_warnings = validate_basis_items(basis.items, evidence_input)
    validation_warnings = [
        {**warning, "stage": "basis", "resolution": "filtered"}
        for warning in validation_warnings
    ]
    if not accepted:
        error = GroundingInvalid(
            "자동 사실성 검증을 통과한 중간 분석 항목이 없습니다.",
            raw_response=basis_raw,
            attempts=basis_attempts,
            validation_warnings=validation_warnings,
        )
        raise error

    accepted_ids = {article_id for item in accepted for article_id in item.articleIds}
    accepted_payload = [item.model_dump() for item in accepted]
    prompt = build_prompt(
        report_date,
        prepared_by,
        evidence_input,
        accepted_payload,
        weather_context=weather_context,
    )
    raw = ""
    last_error = None
    for attempt in range(1, 3):
        current_prompt = (
            prompt
            if attempt == 1
            else build_correction_prompt(prompt, raw, str(last_error or "schema invalid"))
        )
        raw = client.generate(
            model=model,
            prompt=current_prompt,
            format_schema=AnalysisResult.model_json_schema(),
            cancel_token=cancel_token,
        )
        try:
            result = _parse_and_validate(raw, accepted_ids)
            final_warnings = validate_final_result(result, evidence_input, accepted)
            if final_warnings:
                validation_warnings.extend(
                    {**warning, "stage": "final", "resolution": "correction_requested"}
                    for warning in final_warnings
                )
                raise GroundingInvalid(
                    json.dumps(final_warnings, ensure_ascii=False),
                    raw_response=raw,
                    validation_warnings=validation_warnings,
                )
            for warning in validation_warnings:
                if warning.get("stage") == "final" and warning.get("resolution") == "correction_requested":
                    warning["resolution"] = "corrected"
            weather_message, weather_warning = validated_weather_message(
                result.weatherManagementMessage.model_dump(),
                weather_context,
                weather_fallback or {"text": "", "weatherSignalIds": []},
            )
            if weather_warning:
                validation_warnings.append(weather_warning)
            result.weatherManagementMessage = type(result.weatherManagementMessage)(
                **weather_message
            )
            return AnalysisOutput(
                result=result.model_dump(),
                basis={
                    "items": accepted_payload,
                    "limitations": [item.model_dump() for item in basis.limitations],
                    "confidence": basis.confidence,
                },
                validation_warnings=validation_warnings,
                raw_response=raw,
                attempts=attempt,
                basis_attempts=basis_attempts,
            )
        except AnalysisError as exc:
            last_error = exc
    assert last_error is not None
    last_error.attempts = 2
    last_error.raw_response = raw
    raise last_error


def format_analysis(result: dict[str, Any]) -> str:
    def claim_text(value: Any) -> str:
        return str(value.get("text", "")).strip() if isinstance(value, dict) else ""

    management = result.get("managementMessage") or {}
    situation = result.get("situationSummary") or {}
    management_references: list[str] = []
    for item in result.get("actionItems") or []:
        if item.get("kescoJurisdiction") not in {None, "DIRECT", "COLLABORATIVE"}:
            continue
        if item.get("ownerType") == "EXTERNAL_AGENCY":
            continue
        action = str(item.get("action") or "").strip()
        if action:
            management_references.append(action)

    references: list[str] = []
    for item in result.get("keyIssues") or []:
        if item.get("urgency") != "reference" and item.get("kescoJurisdiction") != "MONITORING":
            continue
        summary = str(item.get("summary") or "").strip()
        impact = str(item.get("managementImpact") or "").strip()
        text = " ".join(part for part in (summary, impact) if part)
        if text:
            references.append(text)

    lines = [
        "① 오늘 한줄",
        claim_text(management) or "핵심 경영메시지를 생성하지 못했습니다.",
        "",
        "② 언론 동향 분석",
        claim_text(situation) or "언론 동향 분석을 생성하지 못했습니다.",
        "",
        "③ 경영 참고사항",
        "\n\n".join(management_references) if management_references else "직접적인 경영 현안은 제한적입니다.",
    ]
    if references:
        lines.extend(("", "④ 참고 동향", "\n\n".join(references)))
    return "\n".join(lines)
