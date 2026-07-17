from __future__ import annotations

import hashlib
from typing import Any

from backend.app.services.ids import make_id

RISK_RULE_VERSION = "weather-official-alert-v1"

HAZARDS = {
    "호우": (
        "heavy_rain",
        ["지하·저지대 전기설비 침수", "누전·감전 위험"],
        ["침수 취약시설 사전점검", "비상연락체계 확인", "침수 전 전원차단 안내 검토"],
    ),
    "태풍": (
        "typhoon",
        ["침수 및 옥외 전기설비 손상", "누전·감전 위험"],
        ["옥외·침수 취약설비 점검", "현장 작업자 안전과 점검일정 확인"],
    ),
    "폭염": (
        "heat",
        ["냉방설비 장시간 사용에 따른 배선·접속부 과열"],
        ["노후 배선·멀티탭·실외기 주변 확인", "취약시설 예방점검 검토"],
    ),
    "강풍": (
        "strong_wind",
        ["옥외 임시전기설비·태양광설비 손상"],
        ["옥외설비 고정상태 확인", "현장 작업일정과 작업자 안전 확인"],
    ),
    "대설": (
        "snow",
        ["습설·결빙에 따른 옥외설비 위험"],
        ["옥외설비와 작업자 이동 안전 확인"],
    ),
    "한파": (
        "cold",
        ["전열기기 사용 증가와 옥외설비 결빙"],
        ["전열기기 과부하 안내", "옥외설비·작업자 안전 확인"],
    ),
    "건조": (
        "dry",
        ["전기적 불꽃 발생 시 화재 확산 가능성"],
        ["산림·야외시설 인접 전기설비 예방점검"],
    ),
}


def _signal_key(alert: dict[str, Any], hazard: str, level: str) -> str:
    raw = "|".join(
        [
            hazard,
            level,
            str(alert.get("issuedAt") or ""),
            str(alert.get("title") or ""),
            ",".join(alert.get("regionIds") or []),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def build_signals(alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    seen: set[str] = set()
    for alert in alerts:
        # 원본 응답(raw)에는 현재특보(t6)와 예비특보(t7)가 함께 들어갈 수 있다.
        # 수집 단계에서 분리한 제목만 판정해야 서로 다른 위험현상이 섞이지 않는다.
        text = str(alert.get("title") or "")
        if "해제" in text:
            continue
        for token, mapping in HAZARDS.items():
            if token not in text:
                continue
            hazard, electrical_risks, checks = mapping
            if "경보" in text and "주의보" not in text and not alert.get("preliminary"):
                level = "critical"
            elif "주의보" in text or alert.get("preliminary"):
                level = "watch"
            else:
                continue
            key = _signal_key(alert, hazard, level)
            if key in seen:
                continue
            seen.add(key)
            signals.append(
                {
                    "id": make_id(),
                    "signalKey": key,
                    "hazard": hazard,
                    "level": level,
                    "startsAt": alert.get("effectiveAt") or alert.get("issuedAt"),
                    "endsAt": alert.get("expiresAt"),
                    "regionIds": alert.get("regionIds") or ["national"],
                    "electricalRisks": electrical_risks,
                    "recommendedChecks": checks,
                    "evidence": [
                        {
                            "provider": "kma_alert",
                            "officialIssuedAt": alert.get("issuedAt"),
                            "title": alert.get("title") or "기상특보 현황",
                        }
                    ],
                    "confidence": "high",
                    "ruleId": "official-warning-severity-v1",
                }
            )
    return signals


def overall_level(signals: list[dict[str, Any]], alert_source_status: str) -> str:
    if any(item["level"] == "critical" for item in signals):
        return "critical"
    if any(item["level"] == "watch" for item in signals):
        return "watch"
    if alert_source_status != "success":
        return "unknown"
    return "normal"
