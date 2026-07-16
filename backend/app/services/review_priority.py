from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

SCORING_VERSION = "review-v1"
MAJOR_OUTLETS = {"연합뉴스", "KBS", "MBC", "SBS", "조선일보", "중앙일보", "동아일보", "한겨레", "경향신문"}

IMPACT_BASELINES = {
    "accident": 80,
    "management_risk": 85,
    "mixed": 85,
    "policy": 75,
    "prevention": 55,
    "achievement": 55,
    "community": 40,
    "general": 25,
}


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _time_rank(value: str | None) -> float:
    parsed = _parse_time(value)
    return parsed.timestamp() if parsed else 0.0


def _urgency(last_seen_at: str | None, status: str | None, adverse: bool, as_of: datetime) -> int:
    last_seen = _parse_time(last_seen_at)
    hours = max(0.0, (as_of - last_seen).total_seconds() / 3600) if last_seen else 999.0
    base = 100 if hours <= 6 else 85 if hours <= 12 else 70 if hours <= 24 else 45 if hours <= 48 else 20
    base += 15 if status == "expanding" else 5 if status == "ongoing" else 0
    if adverse:
        base += 10
    if status == "closed":
        base = min(base, 20)
    return min(100, base)


def _actionability(direct: bool, event_types: set[str], severity: int) -> int:
    adverse = bool(event_types & {"accident", "management_risk", "mixed"})
    if direct and adverse and severity >= 70:
        return 100
    if direct and event_types & {"management_risk", "policy", "mixed"}:
        return 90
    if direct:
        return 70
    if adverse and severity >= 70:
        return 70
    if "policy" in event_types:
        return 65
    if event_types & {"prevention", "achievement"}:
        return 55
    if "community" in event_types:
        return 40
    return 25


def score_issue(item: dict[str, Any], as_of: datetime) -> dict[str, Any]:
    members = item.get("members") or []
    relevance = max((int(member.get("relevanceScore") or 0) for member in members), default=0)
    severity = max((int(member.get("severityScore") or 0) for member in members), default=0)
    event_types = {str(member.get("eventType") or "general") for member in members}
    direct = bool(item.get("directMention"))
    impact = max([severity, *(IMPACT_BASELINES.get(value, 25) for value in event_types)])
    sources = {str(member.get("source") or "").strip() for member in members if member.get("source")}
    coverage = min(100, len(sources) * 12 + (20 if sources & MAJOR_OUTLETS else 0))
    adverse = bool(event_types & {"accident", "management_risk", "mixed"})
    urgency = _urgency(item.get("lastSeenAt"), item.get("autoStatus"), adverse, as_of)
    actionability = _actionability(direct, event_types, severity)
    raw = round(0.30 * relevance + 0.25 * impact + 0.20 * coverage + 0.15 * urgency + 0.10 * actionability)
    floors: list[str] = []
    caps: list[str] = []
    if direct and adverse and severity >= 70 and raw < 90:
        raw = 90
        floors.append("direct_serious_adverse_90")
    elif not direct and adverse and severity >= 85 and raw < 70:
        raw = 70
        floors.append("electrical_serious_adverse_70")
    if relevance < 40 and not (adverse and severity >= 85) and raw > 39:
        raw = 39
        caps.append("low_relevance_39")
    reasons = {
        "scoringVersion": SCORING_VERSION,
        "components": {
            "relevance": {"score": relevance, "weight": 0.30},
            "managementImpact": {"score": impact, "weight": 0.25, "eventTypes": sorted(event_types)},
            "coverage": {"score": coverage, "weight": 0.20, "distinctSourceCount": len(sources), "majorOutletIncluded": bool(sources & MAJOR_OUTLETS)},
            "urgency": {"score": urgency, "weight": 0.15, "status": item.get("autoStatus")},
            "responseSuitability": {"score": actionability, "weight": 0.10, "recommendedMode": "proactive" if actionability >= 80 else "prepare" if actionability >= 60 else "monitor" if actionability >= 30 else "none"},
        },
        "floors": floors,
        "caps": caps,
    }
    return {**item, "autoReviewScore": raw, "reviewReasons": reasons, "_impact": impact, "_urgency": urgency, "_relevance": relevance}


def _score_stars(score: int) -> int:
    return 5 if score >= 80 else 4 if score >= 65 else 3 if score >= 50 else 2 if score >= 30 else 1


def _rank_stars(rank: int) -> int:
    return 5 if rank <= 10 else 4 if rank <= 20 else 3 if rank <= 40 else 2 if rank <= 100 else 1


def rank_issues(items: list[dict[str, Any]], as_of: datetime) -> list[dict[str, Any]]:
    scored = [score_issue(item, as_of) for item in items]
    scored.sort(
        key=lambda item: (
            -item["autoReviewScore"],
            -item["_impact"],
            -item["_relevance"],
            -item["_urgency"],
            -_time_rank(item.get("lastSeenAt")),
            str(item.get("id") or item.get("autoTitle") or ""),
        )
    )
    for rank, item in enumerate(scored, start=1):
        item["autoReviewRank"] = rank
        item["autoReviewStars"] = min(_score_stars(item["autoReviewScore"]), _rank_stars(rank))
        for key in ("_impact", "_urgency", "_relevance"):
            item.pop(key, None)
    return scored
