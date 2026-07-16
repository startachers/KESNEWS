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
    message_context_terms,
    matched_terms,
)
from backend.app.services.extraction.cleaner import clean_text
from backend.app.services.classification.sentinel import detect_incident_sentinel
from backend.app.services.ids import make_id
from backend.app.services.media import is_yonhap_article
from backend.app.services.normalization.dates import date_value

Article = dict[str, Any]
CLASSIFIER_VERSION = "rules-v10"

PRIORITY_ORDER = {"reference": 0, "review": 1, "required": 2}


def get_relevance(article: Article) -> dict[str, Any]:
    title, full_text = article_text(article)
    sentinel = article.get("_sentinel") or detect_incident_sentinel(article)
    sentinel_incident_type = (sentinel.get("incident") or {}).get("incident_type")

    def authority_context(text: str) -> list[str]:
        message_terms = [
            *message_context_terms(text, "presidential_message"),
            *message_context_terms(text, "prime_minister_message"),
            *message_context_terms(text, "climate_minister_message"),
        ]
        if message_terms:
            return list(dict.fromkeys(message_terms))
        authority_terms = (
            "국무회의",
            "국정현안관계장관회의",
            "경제관계장관회의",
            "공공기관운영위원회",
            "에너지위원회",
            "전력정책심의회",
            "국회",
            "국정감사",
            "국정조사",
            "현안질의",
        )
        for sentence in re.split(r"(?<=[.!?。！？])\s+|\n+", text):
            authorities = matched_terms(sentence, authority_terms)
            context = sentence
            for term in authority_terms:
                context = context.replace(term, " ")
            energy = matched_terms(
                context,
                (
                    "전기안전",
                    "전력",
                    "전력망",
                    "전력수급",
                    "전기설비",
                    "전기화재",
                    "감전",
                    "정전",
                    "에너지",
                    "ess",
                    "전기차 충전",
                ),
            )
            if authorities and energy:
                return [*authorities, *energy]
        return []

    def industry_strategy_or_macro(text: str) -> list[str]:
        industry = matched_terms(text, ("ess", "에너지저장장치", "배터리", "전기차 충전"))
        safety = matched_terms(text, ("화재", "감전", "폭발", "사고", "안전점검", "결함", "리콜"))
        strategy = matched_terms(
            text,
            ("전력망", "송전망", "배전망", "분산에너지", "데이터센터", "재생에너지", "전력수요"),
        )
        strategy_context = matched_terms(
            text, ("전기안전", "안전관리", "전기설비", "화재", "정전", "검사", "규제", "기본계획")
        )
        if industry and safety:
            return [*industry, *safety]
        if strategy and strategy_context:
            return [*strategy, *strategy_context]
        renewable = matched_terms(
            text,
            ("재생에너지", "태양광", "풍력", "ess", "에너지저장장치", "무정전전원장치"),
        )
        if re.search(r"(?<![a-z0-9])ups(?![a-z0-9])", text):
            renewable.append("ups")
        renewable_context = matched_terms(
            text, ("보급", "확대", "정책", "시장", "투자", "구축", "입찰", "검사", "인증", "안전")
        )
        if renewable and renewable_context:
            return [*renewable, *renewable_context]
        ev = matched_terms(text, ("전기차", "전기자동차"))
        ev_context = matched_terms(
            text, ("보급", "충전소", "충전기", "충전인프라", "배터리", "보조금", "정책", "안전")
        )
        if ev and ev_context:
            return [*ev, *ev_context]
        economy = matched_terms(
            text, ("전기요금", "에너지요금", "공공요금", "유가", "물가", "금리", "경제성장률")
        )
        economy_context = matched_terms(text, ("인상", "인하", "전망", "발표", "정책", "대책"))
        if economy and economy_context:
            return [*economy, *economy_context]
        ai = matched_terms(text, ("인공지능",))
        if re.search(r"(?<![a-z0-9])ai(?![a-z0-9])", text):
            ai.append("ai")
        ai_context = matched_terms(
            text, ("데이터센터", "전력수요", "전력망", "에너지", "안전점검", "안전관리", "공공기관", "정부")
        )
        if ai and ai_context:
            return [*ai, *ai_context]
        return []

    criteria = [
        (
            1,
            "direct_mention",
            "① 공사 직접 거론",
            lambda text: matched_terms(text, ORGANIZATION_TERMS),
        ),
        (
            2,
            "electrical_accident",
            "② 전기화재·감전 사고",
            lambda text: re.findall(
                r"전기[\s·ㆍ-]*화재|누전[\s·ㆍ-]*화재|전기적 요인|감전[\s·ㆍ-]*(?:사고|사망)|배전반[\s·ㆍ-]*화재|변압기[\s·ㆍ-]*화재",
                text,
            ),
        ),
        (
            3,
            "major_fire_sentinel" if sentinel_incident_type == "fire" else "power_outage",
            "③ 중대화재 Sentinel"
            if sentinel_incident_type == "fire"
            else "③ 정전·전력공급 장애",
            lambda text: (["사고 Sentinel"] if sentinel["matched"] else []) + re.findall(
                r"대규모[\s·ㆍ-]*정전|광역[\s·ㆍ-]*정전|일대[\s·ㆍ-]*정전|전력[\s·ㆍ-]*공급[\s·ㆍ-]*중단|전력망[\s·ㆍ-]*장애|계통[\s·ㆍ-]*장애|블랙아웃|변전소[\s·ㆍ-]*고장|송전선로[\s·ㆍ-]*고장|배전선로[\s·ㆍ-]*고장",
                text,
            ),
        ),
        (4, "government_energy_context", "④ 정부·국회+전기·에너지 문맥", authority_context),
        (
            5,
            "law_standard_plan",
            "⑤ 전기 관련 법령·기준·기본계획",
            lambda text: re.findall(
                r"전기안전관리법|전기사업법|한국전기설비규정|\bkec\b|전기설비기술기준|전기안전관리 기본계획|전력수급기본계획",
                text,
            ),
        ),
        (
            6,
            "public_management",
            "⑥ 공공기관 경영평가·운영정책",
            lambda text: re.findall(
                r"공공기관 경영실적 평가|공공기관 경영평가|경영평가편람|경영평가 결과|경영실적 평가결과|공공기관운영위원회|예산운용지침|총인건비|직무급|성과급|안전관리등급|경영공시|\balio\b",
                text,
            ),
        ),
        (
            7,
            "industry_strategy_or_macro",
            "⑦ 신산업·전략·거시환경 동향",
            industry_strategy_or_macro,
        ),
    ]
    matches = [
        (rank, rule, reason, finder(full_text))
        for rank, rule, reason, finder in criteria
        if finder(full_text)
    ]
    if not matches:
        return {
            "rank": 99,
            "score": 15,
            "label": "낮음",
            "tier": "low",
            "directMention": False,
            "titleMatch": False,
            "matchCount": 0,
            "matchedTerms": [],
            "ruleIds": ["relevance_low"],
            "reasons": ["지정 관련도 기준 미일치"],
        }
    primary_rank, primary_rule, _, primary_terms = matches[0]
    primary_finder = criteria[primary_rank - 1][3]
    title_match = bool(primary_finder(title))
    base_score = {1: 100, 2: 88, 3: 80, 4: 65, 5: 55, 6: 45, 7: 40}[primary_rank]
    score = (
        100
        if primary_rank == 1
        else min(99, base_score + (7 if title_match else 0) + min(5, (len(matches) - 1) * 2))
    )
    direct = primary_rank == 1
    return {
        "rank": primary_rank,
        "score": score,
        "label": "매우 높음"
        if direct
        else "높음"
        if primary_rank <= 3
        else "보통"
        if primary_rank <= 5
        else "관심",
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
    if re.search(r"사망|숨져|숨진|목숨을\s*잃|중상|중대재해|다수\s*인명피해", text):
        return (
            100,
            "death_or_serious_injury",
            re.findall(r"사망|숨져|숨진|목숨을\s*잃|중상|중대재해|다수\s*인명피해", text),
        )
    if "대규모 정전" in text or (
        has_actual_accident(text) and re.search(r"전기[\s·ㆍ-]*화재|중대\s*화재", text)
    ):
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
        return (
            5,
            "achievement_or_community",
            matched_terms(text, (*ACHIEVEMENT_TERMS, *COMMUNITY_TERMS)),
        )
    return 10, "prevention_or_routine", []


def _threshold_priority(score: int) -> str:
    return "required" if score >= 75 else "review" if score >= 45 else "reference"


def _raise_priority(priority: str, minimum: str) -> str:
    return minimum if PRIORITY_ORDER[minimum] > PRIORITY_ORDER[priority] else priority


def _lower_priority(priority: str, maximum: str) -> str:
    return maximum if PRIORITY_ORDER[maximum] < PRIORITY_ORDER[priority] else priority


def assess_article(article: Article) -> dict[str, Any]:
    sentinel = article.get("_sentinel") or detect_incident_sentinel(article)
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

    # 직접 수집해 공식 도메인 검증까지 마친 정부부처 자료는 내용 키워드가 약해도
    # 담당자가 반드시 한 번 검토한다. 관련도만으로 required를 만들지는 않는다.
    if article.get("_official_government") is True:
        priority = _raise_priority(priority, "review")
        floors.append("official_government_source")

    _, text = article_text(article)
    serious_direct = relevance["directMention"] and severity_score >= 70
    audit_direct = relevance["directMention"] and bool(matched_terms(text, MANAGEMENT_RISK_PHRASES))
    electrical_domain_accident = bool(
        re.search(r"전기[\s·ㆍ-]*화재|감전|누전|대규모\s*정전|정전\s*발생", text)
    )
    electrical_casualty = (
        electrical_domain_accident and event_type in {"accident", "mixed"} and severity_score >= 85
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
    positive_context = (
        bool(matched_terms(full_text, ACHIEVEMENT_TERMS)) or event_type == "community"
    )
    tone = (
        "negative"
        if severity_score >= 45 or event_type in {"accident", "mixed"}
        else "positive"
        if positive_context
        else "neutral"
    )
    category = infer_category(article)
    reasons = {
        "ruleIds": [*relevance["ruleIds"], *event_rules, severity_rule, *caps, *floors],
        "matchedTerms": list(dict.fromkeys([*relevance["matchedTerms"], *severity_terms])),
        "relevanceTier": relevance["tier"],
        "directMention": relevance["directMention"],
        "relevanceRank": relevance["rank"],
        "relevanceLabel": relevance["label"],
        "relevanceTitleMatch": relevance["titleMatch"],
        "relevanceMatchCount": relevance["matchCount"],
        "relevanceReasons": relevance["reasons"],
        "breakdown": {
            "relevanceScore": relevance["score"],
            "severityScore": severity_score,
            "articleWeights": {"relevance": 0.55, "severity": 0.45},
            "priorityScore": priority_score,
        },
        "appliedCaps": caps,
        "appliedFloors": floors,
    }
    return {
        "autoCategory": category,
        "autoEventType": event_type,
        "autoRelevanceScore": relevance["score"],
        "autoSeverityScore": severity_score,
        "autoPriorityScore": priority_score,
        "autoPriority": priority,
        "autoTone": tone,
        "autoReasons": reasons,
        "incident": sentinel["incident"],
    }


def classify_article(
    raw: Article, risk_keywords: list[str] | None = None, positive_keywords: list[str] | None = None
) -> Article:
    assessment = assess_article(raw)
    legacy_risk = {"required": "critical", "review": "watch", "reference": "routine"}[
        assessment["autoPriority"]
    ]
    return {
        **raw,
        "_sentinel": raw.get("_sentinel") or detect_incident_sentinel(raw),
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
