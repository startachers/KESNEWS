from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import ValidationError

from backend.app.services.ai.prompt_builder import build_correction_prompt, build_prompt
from backend.app.services.ai.schemas import AnalysisResult, validate_evidence


class AiClient(Protocol):
    def generate(self, *, model: str, prompt: str) -> str: ...


class AnalysisError(Exception):
    code = "AI_SCHEMA_INVALID"

    def __init__(self, message: str, *, raw_response: str | None = None, attempts: int = 0):
        super().__init__(message)
        self.raw_response = raw_response
        self.attempts = attempts


class EvidenceInvalid(AnalysisError):
    code = "AI_EVIDENCE_INVALID"


@dataclass(frozen=True)
class AnalysisOutput:
    result: dict[str, Any]
    raw_response: str
    attempts: int


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
                "content": article.get("description") or "",
                "bodyStatus": "summary_only" if article.get("description") else "missing",
                "editorNote": article.get("note") or "",
                "priority": article.get("priority") or article.get("risk") or "reference",
                "issueIds": issue_ids_by_article.get(article_id, []),
            }
        )
    return inputs, evidence


def input_signature(
    model: str, evidence_input: list[dict[str, Any]], context_length: int | None = None
) -> str:
    signature_input: dict[str, Any] = {"model": model, "articles": evidence_input}
    if context_length is not None:
        signature_input["contextLength"] = context_length
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


def analyze(
    client: AiClient,
    *,
    model: str,
    report_date: str,
    prepared_by: str,
    evidence_input: list[dict[str, Any]],
    evidence: dict[str, str],
) -> AnalysisOutput:
    prompt = build_prompt(report_date, prepared_by, evidence_input)
    last_error: AnalysisError | None = None
    raw = ""
    for attempt in range(1, 3):
        current_prompt = (
            prompt
            if attempt == 1
            else build_correction_prompt(prompt, raw, str(last_error or "schema invalid"))
        )
        raw = client.generate(model=model, prompt=current_prompt)
        try:
            result = _parse_and_validate(raw, set(evidence))
            return AnalysisOutput(result=result.model_dump(), raw_response=raw, attempts=attempt)
        except AnalysisError as exc:
            last_error = exc
    assert last_error is not None
    last_error.attempts = 2
    last_error.raw_response = raw
    raise last_error


def format_analysis(result: dict[str, Any]) -> str:
    def claim_text(value: Any) -> str:
        return value.get("text", "") if isinstance(value, dict) else ""

    management = result.get("managementMessage") or {}
    lines = [claim_text(management) or "핵심 경영메시지를 생성하지 못했습니다."]
    situation = result.get("situationSummary") or {}
    if claim_text(situation):
        lines.extend(("", "■ 핵심 상황", claim_text(situation)))
    if result.get("keyIssues"):
        lines.extend(("", "■ 핵심 이슈"))
        for index, item in enumerate(result["keyIssues"], start=1):
            ids = ", ".join(item.get("articleIds") or [])
            lines.extend(
                (
                    f"{index}. {item['title']} ({item['urgency']}) [근거 {ids}]",
                    f"   {item['summary']}",
                    f"   경영 영향: {item['managementImpact']}",
                )
            )
    if result.get("decisionPoints"):
        lines.extend(("", "■ 경영 판단 포인트"))
        for item in result["decisionPoints"]:
            lines.append(f"• {item['text']} [근거 {', '.join(item['articleIds'])}]")
    if result.get("actionItems"):
        lines.extend(("", "■ 확인·지시 필요사항"))
        for item in result["actionItems"]:
            lines.append(
                f"• [{item['priority']}] {item['action']} [근거 {', '.join(item['articleIds'])}]"
            )
    outlook = result.get("riskOutlook") or {}
    if claim_text(outlook):
        lines.extend(
            ("", "■ 위험 전망", f"{claim_text(outlook)} [근거 {', '.join(outlook['articleIds'])}]")
        )
    limitations = [item.get("text", "") for item in result.get("limitations") or [] if item.get("text")]
    if limitations:
        lines.extend(("", f"※ 분석 한계: {' · '.join(limitations)}"))
    return "\n".join(lines)
