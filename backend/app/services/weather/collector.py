from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from typing import Any

from backend.app.services.weather.kma_client import (
    HttpGetter,
    build_daily_summaries,
    collect_alerts,
    collect_mid,
    collect_short,
    http_get,
)
from backend.app.services.weather.region_config import load_regions
from backend.app.services.weather.risk_engine import (
    RISK_RULE_VERSION,
    build_signals,
    overall_level,
)


def collect(service_key: str, report_date: str, getter: HttpGetter = http_get) -> dict[str, Any]:
    config = load_regions()
    regions = config["regions"]
    providers = [
        collect_alerts(service_key, regions, getter),
        collect_short(service_key, regions, getter),
        collect_mid(service_key, regions, getter),
    ]
    alerts_provider, short_provider, mid_provider = providers
    alerts = alerts_provider["items"]
    signals = build_signals(alerts)
    days = build_daily_summaries(
        report_date, short_provider["items"], mid_provider["items"], regions
    )
    source_status = {
        item["provider"]: {
            "status": item["status"],
            "issuedAt": item.get("issuedAt"),
            "error": item.get("error"),
        }
        for item in providers
    }
    level = overall_level(signals, alerts_provider["status"])
    affected_by_day: dict[str, set[str]] = {}
    for signal in signals:
        if not signal.get("startsAt"):
            continue
        day = str(signal["startsAt"])[:10]
        affected_by_day.setdefault(day, set()).update(signal.get("regionIds") or [])
    for day in days:
        affected = affected_by_day.get(day["date"], set())
        day["affectedRegionCount"] = len(affected - {"national"}) or (1 if affected else 0)
        if any(item["level"] == "critical" and str(item.get("startsAt") or "")[:10] == day["date"] for item in signals):
            day["riskLevel"] = "critical"
        elif any(item["level"] == "watch" and str(item.get("startsAt") or "")[:10] == day["date"] for item in signals):
            day["riskLevel"] = "watch"
        elif alerts_provider["status"] != "success":
            # 현재 특보 상태를 확인하지 못했으면 예보가 있어도 안전 상태로 확정하지 않는다.
            day["riskLevel"] = "unknown"
    signature_payload = {
        "sourceStatus": source_status,
        "days": days,
        "alerts": alerts,
        "signals": [{key: value for key, value in signal.items() if key != "id"} for signal in signals],
        "regionConfigVersion": config["version"],
        "riskRuleVersion": RISK_RULE_VERSION,
    }
    raw = json.dumps(signature_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        **signature_payload,
        "providers": providers,
        "overallLevel": level,
        "periodFrom": report_date,
        "periodTo": (date.fromisoformat(report_date) + timedelta(days=6)).isoformat(),
        "issuedAt": max(
            (
                item.get("issuedAt")
                for item in providers
                if item["status"] != "failed" and item.get("issuedAt")
            ),
            default=None,
        ),
        "inputSignature": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
    }
