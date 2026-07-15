from __future__ import annotations

import re
import unicodedata
from typing import Any

from backend.app.services.extraction.cleaner import clean_text

ORGANIZATION_TERMS = ("한국전기안전공사", "전기안전공사", "KESCO")
OCCURRENCE_CUES = ("발생", "사망", "부상", "중상", "인명피해", "피해", "대피", "중단", "수사", "압수수색", "적발")
ACCIDENT_TERMS = ("전기화재", "전기 화재", "화재", "감전사고", "감전 사고", "감전", "대규모 정전", "정전 발생", "누전 사고")
MANAGEMENT_RISK_PHRASES = ("감사원 감사", "감사 결과", "국정감사", "수사 결과", "압수수색", "고발", "징계", "법 위반")
PREVENTION_CUES = ("예방", "점검", "교육", "캠페인", "훈련")
ACHIEVEMENT_TERMS = ("수상", "성과", "혁신", "우수", "개선")
COMMUNITY_TERMS = ("협약", "봉사", "지원", "지역", "상생")
POLICY_TERMS = ("산업통상", "전기안전관리법", "정책", "규제", "법안", "국회")
HARD_EXCLUSION_PHRASES = ("채용공고",)

_CATEGORY_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("safety", ("화재", "감전", "사고", "안전점검", "누전", "정전", "재해")),
    ("management", ("사장", "감사원 감사", "국정감사", "경영평가", "인사", "채용", "노조", "비위")),
    ("policy", POLICY_TERMS),
    ("industry", ("태양광", "ess", "전기차", "배터리", "신재생", "충전시설")),
    ("community", ("협약", "봉사", "지원", "캠페인", "지역", "상생")),
]


def normalized_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", clean_text(value or "")).lower()).strip()


def article_text(article: dict[str, Any]) -> tuple[str, str]:
    title = normalized_text(str(article.get("title") or ""))
    description = normalized_text(str(article.get("description") or article.get("bodyText") or ""))
    return title, f"{title}. {description}".strip()


def matched_terms(text: str, terms: tuple[str, ...]) -> list[str]:
    return [term for term in terms if term.lower() in text]


def sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?。！？])\s+|\n+", text) if part.strip()] or [text]


def has_actual_accident(text: str) -> bool:
    """예방 문구와 분리된 문장에 위해 용어와 발생 신호가 함께 있을 때만 사고로 본다."""
    for sentence in sentences(text):
        accidents = matched_terms(sentence, ACCIDENT_TERMS)
        occurrences = matched_terms(sentence, OCCURRENCE_CUES)
        if not accidents and not any(term in sentence for term in ("사망", "부상", "중상", "인명피해")):
            continue
        if occurrences:
            return True
    return False


def infer_event_type(article: dict[str, Any]) -> tuple[str, list[str]]:
    _, text = article_text(article)
    actual_accident = has_actual_accident(text)
    management_matches = matched_terms(text, MANAGEMENT_RISK_PHRASES)
    prevention_matches = matched_terms(text, PREVENTION_CUES)
    achievement_matches = matched_terms(text, ACHIEVEMENT_TERMS)
    community_matches = matched_terms(text, COMMUNITY_TERMS)

    if actual_accident:
        event_type = "mixed" if prevention_matches else "accident"
        rules = ["explicit_adverse_event"]
        if prevention_matches:
            rules.append("prevention_context_preserved")
    elif management_matches:
        event_type, rules = "management_risk", ["management_risk"]
    elif prevention_matches:
        event_type, rules = "prevention", ["prevention_context"]
    elif achievement_matches:
        event_type, rules = "achievement", ["achievement_context"]
    elif community_matches:
        event_type, rules = "community", ["community_context"]
    elif matched_terms(text, POLICY_TERMS):
        event_type, rules = "policy", ["policy_context"]
    else:
        event_type, rules = "general", ["general_fallback"]
    return event_type, rules


def infer_category(article: dict[str, Any]) -> str:
    _, text = article_text(article)
    # '감사패' 속 모호한 '감사'는 management로 쓰지 않는다. 구체 문구는 그대로 남는다.
    suppressed = text.replace("감사패", " ").replace("감사 인사", " ")
    for category, keywords in _CATEGORY_RULES:
        if any(keyword in suppressed for keyword in keywords):
            return category
    return "direct"


def should_exclude(article: dict[str, Any], exclude_keywords: list[str]) -> bool:
    _, text = article_text(article)
    keywords = [*HARD_EXCLUSION_PHRASES, *(keyword.strip().lower() for keyword in exclude_keywords)]
    return any(keyword and keyword in text for keyword in keywords)
