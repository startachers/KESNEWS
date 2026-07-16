from __future__ import annotations

import re
import unicodedata
from typing import Any

from backend.app.services.extraction.cleaner import clean_text
from backend.app.services.classification.sentinel import detect_incident_sentinel

ORGANIZATION_TERMS = ("한국전기안전공사", "전기안전공사", "KESCO")
OCCURRENCE_CUES = (
    "발생",
    "사망",
    "숨져",
    "숨진",
    "목숨을 잃",
    "부상",
    "중상",
    "인명피해",
    "피해",
    "대피",
    "중단",
    "수사",
    "압수수색",
    "적발",
)
ACCIDENT_TERMS = (
    "전기화재",
    "전기 화재",
    "화재",
    "감전사고",
    "감전 사고",
    "감전",
    "대규모 정전",
    "정전 발생",
    "누전 사고",
)
MANAGEMENT_RISK_PHRASES = (
    "감사원 감사",
    "감사 결과",
    "국정감사",
    "수사 결과",
    "압수수색",
    "고발",
    "징계",
    "법 위반",
)
PREVENTION_CUES = ("예방", "점검", "교육", "캠페인", "훈련")
ACHIEVEMENT_TERMS = ("수상", "성과", "혁신", "우수", "개선")
COMMUNITY_TERMS = ("협약", "봉사", "지원", "지역", "상생")
POLICY_TERMS = ("산업통상", "전기안전관리법", "정책", "규제", "법안", "국회")
HARD_EXCLUSION_PHRASES = ("채용공고",)

_CATEGORY_RULES: list[tuple[str, tuple[tuple[str, ...], ...]]] = [
    (
        "kesco_reputation",
        (
            ORGANIZATION_TERMS,
            (
                "사망",
                "사고",
                "화재",
                "감전",
                "정전",
                "중대재해",
                "부실점검",
                "허위점검",
                "위반",
                "논란",
                "수사",
                "고발",
                "압수수색",
                "징계",
                "비위",
                "해킹",
                "정보 유출",
                "민원",
            ),
        ),
    ),
    (
        "kesco_governance",
        (
            ORGANIZATION_TERMS,
            (
                "경영평가",
                "경영공시",
                "국정감사",
                "감사원",
                "이사회",
                "기관장",
                "사장",
                "상임감사",
                "임원",
                "인사",
                "노사",
                "노조",
                "파업",
                "예산",
                "총인건비",
                "직무급",
                "성과급",
            ),
        ),
    ),
    (
        "kesco_achievement",
        (
            ORGANIZATION_TERMS,
            (
                "업무협약",
                "협약",
                "수상",
                "혁신",
                "합동점검",
                "특별점검",
                "예방점검",
                "캠페인",
                "봉사",
                "기부",
                "상생",
                "안전문화",
                "취약계층",
            ),
        ),
    ),
    (
        "presidential_message",
        (
            ("대통령실", "대통령"),
            (
                "전기안전",
                "전력망",
                "전력수급",
                "전기설비",
                "전기화재",
                "감전",
                "정전",
                "ess",
                "전기차 충전",
            ),
        ),
    ),
    (
        "prime_minister_message",
        (
            ("국무총리", "총리실", "국무조정실"),
            ("전기안전", "전력망", "전력수급", "전기설비", "전기화재", "감전", "정전"),
        ),
    ),
    (
        "climate_minister_message",
        (
            ("기후에너지환경부",),
            (
                "전기안전",
                "전력망",
                "전력수급",
                "전기설비",
                "전기화재",
                "감전",
                "정전",
                "ess",
                "전기차 충전",
                "재생에너지",
            ),
        ),
    ),
    (
        "government_meeting",
        (
            (
                "국무회의",
                "국정현안관계장관회의",
                "경제관계장관회의",
                "공공기관운영위원회",
                "에너지위원회",
                "전력정책심의회",
            ),
            ("전기안전", "전력", "전력망", "전력수급", "전기설비", "정전", "공공기관"),
        ),
    ),
    (
        "assembly_law",
        (
            ("국회", "국정감사", "국정조사", "법안", "개정안", "입법예고", "현안질의"),
            ("전기안전", "전기화재", "감전", "정전", "전력망", "전기설비", "한국전기안전공사"),
        ),
    ),
    (
        "electrical_accident",
        (
            (
                "전기화재",
                "전기 화재",
                "누전 화재",
                "전기적 요인",
                "감전사고",
                "감전 사고",
                "감전 사망",
                "배전반 화재",
                "변압기 화재",
            ),
        ),
    ),
    (
        "power_outage",
        (
            (
                "대규모 정전",
                "광역 정전",
                "일대 정전",
                "전력 공급 중단",
                "전력망 장애",
                "계통 장애",
                "블랙아웃",
                "변전소 고장",
                "송전선로 고장",
                "배전선로 고장",
            ),
        ),
    ),
    (
        "major_fire_breaking",
        (
            ("화재", "폭발", "큰불"),
            (
                "사망",
                "숨져",
                "사상",
                "중상",
                "심정지",
                "실종",
                "전소",
                "대피",
                "대응 1단계",
                "대응 2단계",
                "대응 3단계",
            ),
        ),
    ),
    (
        "new_industry_safety",
        (
            ("ess", "에너지저장장치", "배터리", "전기차 충전"),
            ("화재", "감전", "폭발", "사고", "안전점검", "결함", "리콜"),
        ),
    ),
    (
        "law_standard_plan",
        (
            (
                "전기안전관리법",
                "전기사업법",
                "한국전기설비규정",
                "kec",
                "전기설비기술기준",
                "전기안전관리 기본계획",
                "전력수급기본계획",
            ),
        ),
    ),
    (
        "public_evaluation",
        (
            (
                "공공기관 경영실적 평가",
                "공공기관 경영평가",
                "경영평가편람",
                "경영평가 결과",
                "경영실적 평가결과",
            ),
        ),
    ),
    (
        "public_operations",
        (
            ("공공기관", "공기업", "준정부기관"),
            (
                "공공기관운영위원회",
                "예산운용지침",
                "총인건비",
                "직무급",
                "성과급",
                "안전관리등급",
                "경영공시",
                "alio",
            ),
        ),
    ),
    (
        "strategic_trend",
        (
            ("전력망", "송전망", "배전망", "분산에너지", "데이터센터", "재생에너지", "전력수요"),
            ("전기안전", "안전관리", "전기설비", "화재", "정전", "검사", "규제", "기본계획"),
        ),
    ),
    ("kesco_direct", (ORGANIZATION_TERMS,)),
]


def normalized_text(value: str | None) -> str:
    return re.sub(
        r"\s+", " ", unicodedata.normalize("NFKC", clean_text(value or "")).lower()
    ).strip()


def article_text(article: dict[str, Any]) -> tuple[str, str]:
    title = normalized_text(str(article.get("title") or ""))
    description = normalized_text(str(article.get("description") or article.get("bodyText") or ""))
    return title, f"{title}. {description}".strip()


def matched_terms(text: str, terms: tuple[str, ...]) -> list[str]:
    return [term for term in terms if term.lower() in text]


def sentences(text: str) -> list[str]:
    return [
        part.strip() for part in re.split(r"(?<=[.!?。！？])\s+|\n+", text) if part.strip()
    ] or [text]


def has_actual_accident(text: str) -> bool:
    """예방 문구와 분리된 문장에 위해 용어와 발생 신호가 함께 있을 때만 사고로 본다."""
    for sentence in sentences(text):
        accident_text = (
            sentence.replace("삼성화재", " ")
            .replace("화재보험", " ")
            .replace("화재대피안심콜", " ")
        )
        accidents = matched_terms(accident_text, ACCIDENT_TERMS)
        occurrences = matched_terms(sentence, OCCURRENCE_CUES)
        explicit_occurrence = bool(
            re.search(
                r"(?:화재|폭발|감전)(?:가|이|로|으로|해|하여|하면서|\s*중)|"
                r"(?:작업|운전|가동|충전|사용)?\s*중\s*(?:화재|폭발|감전)|"
                r"(?:불|불길)(?:이|이\s*)?(?:나|났|붙)",
                accident_text,
            )
        )
        if not accidents and not any(
            term in sentence for term in ("사망", "부상", "중상", "인명피해")
        ):
            continue
        if occurrences or explicit_occurrence:
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
    if (
        matched_terms(suppressed, ORGANIZATION_TERMS)
        and matched_terms(suppressed, (*ACHIEVEMENT_TERMS, *COMMUNITY_TERMS, *PREVENTION_CUES))
        and not has_actual_accident(suppressed)
    ):
        return "kesco_achievement"
    prevention_only = bool(matched_terms(suppressed, PREVENTION_CUES)) and not has_actual_accident(
        suppressed
    )
    for category, required_groups in _CATEGORY_RULES:
        if prevention_only and category in {"electrical_accident", "major_fire_breaking"}:
            continue
        if category == "major_fire_breaking" and not detect_incident_sentinel(article)["matched"]:
            continue
        if all(
            any(keyword.lower() in suppressed for keyword in group) for group in required_groups
        ):
            return category
    return "other"


def should_exclude(article: dict[str, Any], exclude_keywords: list[str]) -> bool:
    _, text = article_text(article)
    keywords = [*HARD_EXCLUSION_PHRASES, *(keyword.strip().lower() for keyword in exclude_keywords)]
    return any(keyword and keyword in text for keyword in keywords)
