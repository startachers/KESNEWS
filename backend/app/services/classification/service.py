from __future__ import annotations

import re
from functools import cmp_to_key
from typing import Any

from backend.app.core.clock import now_iso
from backend.app.services.classification.rule_engine import (
    ACCIDENT_TERMS,
    ACHIEVEMENT_TERMS,
    COMMUNITY_TERMS,
    MANAGEMENT_RISK_PHRASES,
    ORGANIZATION_TERMS,
    PREVENTION_CUES,
    article_text,
    has_actual_accident,
    infer_category,
    infer_event_type,
    matched_terms,
)
from backend.app.services.extraction.cleaner import clean_text
from backend.app.services.ids import make_id
from backend.app.services.media import is_yonhap_article
from backend.app.services.normalization.dates import date_value

Article = dict[str, Any]
CLASSIFIER_VERSION = "rules-v2"

PRIORITY_ORDER = {"reference": 0, "review": 1, "required": 2}


def get_relevance(article: Article) -> dict[str, Any]:
    title, full_text = article_text(article)

    criteria = [
        (1, "direct_mention", "① 공사 직접 거론", lambda text: matched_terms(text, ORGANIZATION_TERMS)),
        (2, "electrical_fire", "② 전기화재", lambda text: re.findall(r"전기[\s·ㆍ-]*화재", text)),
        (3, "electric_shock", "③ 감전사고", lambda text: re.findall(r"감전[\s·ㆍ-]*사고", text)),
        (4, "ministry_policy_context", "④ 기후에너지환경부+에너지/전기", lambda text: ["기후에너지환경부"] if "기후에너지환경부" in text and re.search(r"에너지|전기", text.replace("기후에너지환경부", " ")) else []),
        (5, "renewable_energy", "⑤ 재생에너지", lambda text: re.findall(r"재생[\s·ㆍ-]*에너지", text)),
    ]
    matches = [(rank, rule, reason, finder(full_text)) for rank, rule, reason, finder in criteria if finder(full_text)]
    if not matches:
        return {"rank": 99, "score": 15, "label": "낮음", "tier": "low", "directMention": False, "titleMatch": False, "matchCount": 0, "matchedTerms": [], "ruleIds": ["relevance_low"], "reasons": ["지정 관련도 기준 미일치"]}
    primary_rank, primary_rule, _, primary_terms = matches[0]
    primary_finder = criteria[primary_rank - 1][3]
    title_match = bool(primary_finder(title))
    base_score = {1: 100, 2: 85, 3: 70, 4: 55, 5: 40}[primary_rank]
    score = 100 if primary_rank == 1 else min(99, base_score + (7 if title_match else 0) + min(5, (len(matches) - 1) * 2))
    direct = primary_rank == 1
    return {
        "rank": primary_rank,
        "score": score,
        "label": "매우 높음" if direct else "높음" if primary_rank <= 3 else "보통" if primary_rank == 4 else "관심",
        "tier": "direct" if direct else "related" if score >= 40 else "low",
        "directMention": direct,
        "titleMatch": title_match,
        "matchCount": len(matches),
        "matchedTerms": list(dict.fromkeys(term for *_, terms in matches for term in terms)),
        "ruleIds": [rule for _, rule, _, _ in matches] or [primary_rule],
        "reasons": [reason for _, _, reason, _ in matches],
    }


def _severity(article: Article, event_type: str) -> tuple[int, str, list[str]]:
    _, text = article_text(article)
    if re.search(r"사망|중상|중대재해|다수\s*인명피해", text):
        return 100, "death_or_serious_injury", re.findall(r"사망|중상|중대재해|다수\s*인명피해", text)
    if "대규모 정전" in text or (has_actual_accident(text) and re.search(r"전기[\s·ㆍ-]*화재|중대\s*화재", text)):
        return 85, "major_fire_or_outage", matched_terms(text, (*ACCIDENT_TERMS, "중대화재"))
    if re.search(r"수사|압수수색", text):
        return 80, "investigation_or_raid", re.findall(r"수사|압수수색", text)
    if matched_terms(text, MANAGEMENT_RISK_PHRASES):
        return 65, "audit_or_legal_violation", matched_terms(text, MANAGEMENT_RISK_PHRASES)
    if re.search(r"논란|경미한 피해|소규모 피해", text):
        return 45, "controversy_or_minor_damage", re.findall(r"논란|경미한 피해|소규모 피해", text)
    if event_type in {"prevention", "general", "policy"}:
        return 10, "prevention_or_routine", matched_terms(text, PREVENTION_CUES)
    if event_type in {"achievement", "community"}:
        return 5, "achievement_or_community", matched_terms(text, (*ACHIEVEMENT_TERMS, *COMMUNITY_TERMS))
    return 10, "prevention_or_routine", []


def _threshold_priority(score: int) -> str:
    return "required" if score >= 75 else "review" if score >= 45 else "reference"


def _raise_priority(priority: str, minimum: str) -> str:
    return minimum if PRIORITY_ORDER[minimum] > PRIORITY_ORDER[priority] else priority


def _lower_priority(priority: str, maximum: str) -> str:
    return maximum if PRIORITY_ORDER[maximum] < PRIORITY_ORDER[priority] else priority


def assess_article(article: Article) -> dict[str, Any]:
    relevance = get_relevance(article)
    event_type, event_rules = infer_event_type(article)
    severity_score, severity_rule, severity_terms = _severity(article, event_type)
    priority_score = round(0.55 * relevance["score"] + 0.45 * severity_score)
    priority = _threshold_priority(priority_score)
    caps: list[str] = []
    floors: list[str] = []

    if event_type in {"prevention", "achievement", "community"}:
        caps.append("positive_context_cap")
        capped = _lower_priority(priority, "review")
        priority = capped
    if relevance["tier"] == "low":
        caps.append("low_relevance_cap")
        capped = _lower_priority(priority, "reference")
        priority = capped

    _, text = article_text(article)
    serious_direct = relevance["directMention"] and severity_score >= 70
    audit_direct = relevance["directMention"] and bool(matched_terms(text, MANAGEMENT_RISK_PHRASES))
    electrical_domain_accident = bool(
        re.search(r"전기[\s·ㆍ-]*화재|감전|누전|대규모\s*정전|정전\s*발생", text)
    )
    electrical_casualty = (
        electrical_domain_accident
        and event_type in {"accident", "mixed"}
        and severity_score >= 85
    )
    if serious_direct:
        priority = _raise_priority(priority, "required")
        floors.append("direct_serious_adverse")
    elif audit_direct:
        minimum = "required" if severity_score >= 70 else "review"
        priority = _raise_priority(priority, minimum)
        floors.append("direct_audit_or_legal")
    elif electrical_casualty:
        priority = _raise_priority(priority, "review")
        floors.append("electrical_safety_casualty")

    _, full_text = article_text(article)
    positive_context = bool(matched_terms(full_text, ACHIEVEMENT_TERMS)) or event_type == "community"
    tone = "negative" if severity_score >= 45 else "positive" if positive_context else "neutral"
    category = infer_category(article)
    reasons = {
        "ruleIds": [*relevance["ruleIds"], *event_rules, severity_rule, *caps, *floors],
        "matchedTerms": list(dict.fromkeys([*relevance["matchedTerms"], *severity_terms])),
        "relevanceTier": relevance["tier"],
        "directMention": relevance["directMention"],
        "breakdown": {"relevanceScore": relevance["score"], "severityScore": severity_score, "articleWeights": {"relevance": 0.55, "severity": 0.45}, "priorityScore": priority_score},
        "appliedCaps": caps,
        "appliedFloors": floors,
    }
    return {"autoCategory": category, "autoEventType": event_type, "autoRelevanceScore": relevance["score"], "autoSeverityScore": severity_score, "autoPriorityScore": priority_score, "autoPriority": priority, "autoTone": tone, "autoReasons": reasons}


def classify_article(raw: Article, risk_keywords: list[str] | None = None, positive_keywords: list[str] | None = None) -> Article:
    assessment = assess_article(raw)
    legacy_risk = {"required": "critical", "review": "watch", "reference": "routine"}[assessment["autoPriority"]]
    return {
        **raw,
        "id": raw.get("id") or make_id(),
        "pubDate": raw.get("pubDate") or now_iso(),
        "description": clean_text(raw.get("description") or ""),
        "category": raw.get("category") or assessment["autoCategory"],
        "matchedKeywords": assessment["autoReasons"]["matchedTerms"][:8],
        "risk": legacy_risk,
        "riskScore": assessment["autoSeverityScore"],
        "sentiment": assessment["autoTone"],
        "assessment": assessment,
        "included": raw["included"] if raw.get("included") is not None else bool(raw.get("manual")),
        "starred": bool(raw.get("starred")),
        "note": raw.get("note") or "",
        "manual": bool(raw.get("manual")),
        "isDemo": bool(raw.get("isDemo")),
    }


def _relevance_compare(a: Article, b: Article) -> int:
    left, right = get_relevance(a), get_relevance(b)
    risk_order = {"critical": 3, "watch": 2, "routine": 1}
    diff = (
        (left["rank"] - right["rank"])
        or (int(is_yonhap_article(b)) - int(is_yonhap_article(a)))
        or (int(bool(b.get("starred"))) - int(bool(a.get("starred"))))
        or (int(right["titleMatch"]) - int(left["titleMatch"]))
        or (right["matchCount"] - left["matchCount"])
        or (right["score"] - left["score"])
        or (risk_order.get(b.get("risk"), 0) - risk_order.get(a.get("risk"), 0))
        or (date_value(b.get("pubDate")) - date_value(a.get("pubDate")))
    )
    if diff:
        return -1 if diff < 0 else 1
    left_title, right_title = str(a.get("title") or ""), str(b.get("title") or "")
    title_cmp = -1 if left_title < right_title else 1 if left_title > right_title else 0
    left_id, right_id = str(a.get("id") or ""), str(b.get("id") or "")
    return title_cmp or (-1 if left_id < right_id else 1 if left_id > right_id else 0)


relevance_sort_key = cmp_to_key(_relevance_compare)
