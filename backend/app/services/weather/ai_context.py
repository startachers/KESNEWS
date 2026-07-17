from __future__ import annotations

import hashlib
import json
from typing import Any


def build_weather_ai_context(
    weather: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, dict[str, str], dict[str, Any]]:
    if not weather:
        return None, {}, {"text": "", "weatherSignalIds": []}
    context = weather.get("context") or {}
    attachment = weather.get("attachment") or {}
    signals = context.get("riskSignals") or []
    evidence: dict[str, str] = {}
    normalized_signals: list[dict[str, Any]] = []
    for index, signal in enumerate(signals, start=1):
        evidence_id = f"W{index:02d}"
        evidence[evidence_id] = signal["id"]
        normalized_signals.append(
            {
                **signal,
                "id": evidence_id,
                "weatherSignalId": signal["id"],
            }
        )
    signature_payload = {
        "contextId": context.get("id"),
        "inputSignature": context.get("inputSignature"),
        "sourceIssuedAt": {
            name: item.get("issuedAt")
            for name, item in (context.get("sourceStatus") or {}).items()
        },
        "signals": normalized_signals,
        "editorNote": attachment.get("editorNote") or "",
        "reviewedAt": attachment.get("reviewedAt"),
        "regionConfigVersion": context.get("regionConfigVersion"),
        "riskRuleVersion": context.get("riskRuleVersion"),
    }
    raw = json.dumps(
        signature_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    weather_context = {
        "contextId": context.get("id"),
        "signature": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        "reviewedAt": attachment.get("reviewedAt"),
        "evidence": evidence,
        "riskSignals": normalized_signals,
        "editorNote": attachment.get("editorNote") or "",
    }
    return weather_context, evidence, template_weather_message(normalized_signals)


def template_weather_message(signals: list[dict[str, Any]]) -> dict[str, Any]:
    if not signals:
        return {"text": "", "weatherSignalIds": []}
    parts: list[str] = []
    evidence_ids: list[str] = []
    for signal in signals[:3]:
        evidence_ids.append(signal["id"])
        regions = ", ".join(signal.get("regionIds") or ["전국"])
        risks = ", ".join(signal.get("electricalRisks") or [])
        checks = ", ".join(signal.get("recommendedChecks") or [])
        level = "경보" if signal.get("level") == "critical" else "주의보"
        parts.append(
            f"{regions} {level}에 따라 {risks}에 대한 선제적 대비가 필요합니다. "
            f"{checks}을 우선 확인할 필요가 있습니다."
        )
    return {"text": " ".join(parts), "weatherSignalIds": evidence_ids}


def validated_weather_message(
    candidate: dict[str, Any] | None,
    weather_context: dict[str, Any] | None,
    fallback: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    if not weather_context:
        if candidate and (candidate.get("text") or candidate.get("weatherSignalIds")):
            return fallback, {
                "code": "WEATHER_EVIDENCE_INVALID",
                "field": "weatherManagementMessage",
                "resolution": "template_fallback",
            }
        return fallback, None
    candidate = candidate or {}
    text = str(candidate.get("text") or "").strip()
    ids = candidate.get("weatherSignalIds") or []
    valid_ids = set(weather_context.get("evidence") or {})
    invalid = [item for item in ids if item not in valid_ids]
    linked = [
        item
        for item in weather_context.get("riskSignals") or []
        if item.get("id") in ids
    ]
    invalid_critical = "경보" in text and not any(
        item.get("level") == "critical" for item in linked
    )
    if (text and not ids) or invalid or invalid_critical or (not text and valid_ids):
        return fallback, {
            "code": "WEATHER_EVIDENCE_INVALID",
            "field": "weatherManagementMessage",
            "invalidIds": invalid,
            "resolution": "template_fallback",
        }
    return {"text": text, "weatherSignalIds": ids}, None
