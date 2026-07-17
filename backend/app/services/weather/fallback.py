from __future__ import annotations

import hashlib
import json
from typing import Any

from backend.app.services.weather.risk_engine import build_signals, overall_level


def _merge_partial_regions(
    current: dict[str, Any], previous: dict[str, Any], region_ids: set[str]
) -> dict[str, Any]:
    current_regions = {
        item["regionId"]: dict(item) for item in current.get("regions") or []
    }
    previous_regions = {
        item["regionId"]: dict(item) for item in previous.get("regions") or []
    }
    for region_id in region_ids:
        if region_id in previous_regions:
            current_regions[region_id] = previous_regions[region_id]
    regions = list(current_regions.values())
    temperatures = [item.get("temperature") or {} for item in regions]
    lows = [item["min"] for item in temperatures if item.get("min") is not None]
    highs = [item["max"] for item in temperatures if item.get("max") is not None]
    pops = [
        item["maxPrecipitationProbability"]
        for item in regions
        if item.get("maxPrecipitationProbability") is not None
    ]
    precipitation = [
        item["maxHourlyPrecipitation"]
        for item in regions
        if item.get("maxHourlyPrecipitation")
    ]
    winds = [
        item["maxWindSpeed"]
        for item in regions
        if item.get("maxWindSpeed") is not None
    ]
    weather_values = [item.get("weatherText") for item in regions if item.get("weatherText")]
    weather_text = next(
        (
            value
            for token in ("태풍", "비", "눈", "흐림", "구름")
            for value in weather_values
            if token in value
        ),
        weather_values[0] if weather_values else "정보 없음",
    )
    max_hourly_precipitation = max(
        precipitation,
        key=lambda item: item["max"] if item.get("max") is not None else item.get("min", 0) + 10000,
        default=None,
    )
    return {
        **current,
        "weatherText": weather_text,
        "temperature": {
            "min": min(lows) if lows else None,
            "max": max(highs) if highs else None,
            "isNationalRange": True,
        },
        "maxPrecipitationProbability": max(pops) if pops else None,
        "maxHourlyPrecipitation": max_hourly_precipitation,
        "maxWindSpeed": max(winds) if winds else None,
        "regions": regions,
    }


def reuse_failed_providers(
    result: dict[str, Any], previous: dict[str, Any] | None
) -> dict[str, Any]:
    if not previous:
        return result
    reused: list[str] = []
    source_status = result["sourceStatus"]
    previous_status = previous.get("sourceStatus") or {}
    days = [dict(item) for item in result.get("days") or []]
    previous_days = previous.get("days") or []
    provider_results = {item["provider"]: item for item in result.get("providers") or []}

    if source_status["alerts"]["status"] == "failed" and previous.get("alerts") is not None:
        result["alerts"] = previous.get("alerts") or []
        result["signals"] = build_signals(result["alerts"])
        source_status["alerts"] = {
            **source_status["alerts"],
            "status": "stale",
            "issuedAt": (previous_status.get("alerts") or {}).get("issuedAt"),
        }
        reused.append("alerts")

    for provider, offsets in (("shortForecast", range(0, 4)), ("midForecast", range(4, 7))):
        provider_status = source_status[provider]["status"]
        if provider_status not in {"failed", "partial"}:
            continue
        failed_regions = set(
            (provider_results.get(provider) or {}).get("failedRegionIds") or []
        )
        for offset in offsets:
            if offset < len(previous_days) and offset < len(days):
                if provider_status == "failed":
                    days[offset] = dict(previous_days[offset])
                elif failed_regions:
                    days[offset] = _merge_partial_regions(
                        days[offset], previous_days[offset], failed_regions
                    )
        if provider_status == "failed":
            source_status[provider] = {
                **source_status[provider],
                "status": "stale",
                "issuedAt": (previous_status.get(provider) or {}).get("issuedAt"),
            }
        reused.append(provider)

    if not reused:
        return result
    result["days"] = days
    result["reusedProviders"] = reused
    result["overallLevel"] = overall_level(
        result.get("signals") or [], source_status["alerts"]["status"]
    )
    result["issuedAt"] = max(
        (item.get("issuedAt") for item in source_status.values() if item.get("issuedAt")),
        default=None,
    )
    signature_payload = {
        "sourceStatus": source_status,
        "days": days,
        "alerts": result.get("alerts") or [],
        "signals": [
            {key: value for key, value in signal.items() if key != "id"}
            for signal in result.get("signals") or []
        ],
        "regionConfigVersion": result["regionConfigVersion"],
        "riskRuleVersion": result["riskRuleVersion"],
    }
    raw = json.dumps(
        signature_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    result["inputSignature"] = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return result
