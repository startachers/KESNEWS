from __future__ import annotations

import re
from typing import Any

Article = dict[str, Any]

_FIRE_SIGNALS = ("화재", "큰불", "폭발", "진화")
_FIRE_SEVERITY_SIGNALS = (
    "사망",
    "숨져",
    "사상",
    "중상",
    "심정지",
    "실종",
    "전소",
    "반소",
    "대피",
    "연기흡입",
    "재산피해",
    "피해액",
    "피해 규모",
    "대응 1단계",
    "대응 2단계",
    "대응 3단계",
)
_FIRE_FALSE_POSITIVE_PHRASES = (
    "삼성화재",
    "화재보험",
    "화재대피안심콜",
)
_OUTAGE_SIGNALS = (
    "정전",
    "전력 공급 중단",
    "블랙아웃",
    "변전소 고장",
    "송전선로 고장",
    "배전선로 고장",
    "계통 장애",
)
_OUTAGE_COMPANION_SIGNALS = (
    "세대",
    "가구",
    "병원",
    "공항",
    "철도",
    "지하철",
    "데이터센터",
    "신호등",
    "승강기",
    "산업단지",
    "공장",
    "생산 차질",
    "화재",
    "폭발",
    "감전",
    "복구",
)
_PLANNED_OUTAGE_SIGNALS = (
    "계획정전",
    "정전 예정",
    "정전 안내",
    "정기점검에 따른",
    "전기공사로 인한",
    "정전 대비 훈련",
    "정전 예방",
)
_ACTUAL_OUTAGE_SIGNALS = (
    "정전 발생",
    "갑작스러운 정전",
    "고장",
    "공급 중단",
    "블랙아웃",
    "계통 장애",
    "복구",
    "전력 끊",
    "전기가 끊",
    "생산 차질",
)
_CRITICAL_FACILITIES = (
    "요양병원",
    "병원",
    "학교",
    "유치원",
    "공항",
    "철도",
    "지하철",
    "데이터센터",
    "발전소",
    "변전소",
    "산업단지",
    "물류센터",
    "전통시장",
    "지하주차장",
    "ess",
    "전기차 충전",
)


def _article_text(article: Article) -> str:
    return " ".join(
        str(article.get(field) or "") for field in ("title", "description", "bodyText", "body_text")
    ).lower()


def _first_int(text: str, patterns: tuple[str, ...]) -> int | None:
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return int(match.group(1).replace(",", ""))
    return None


def _critical_facility(text: str) -> str | None:
    return next(
        (
            facility.upper() if facility == "ess" else facility
            for facility in _CRITICAL_FACILITIES
            if facility in text
        ),
        None,
    )


def _property_damage(text: str) -> int | None:
    match = re.search(r"(?:재산피해|피해액)(?:은|이|가)?\s*(\d[\d,]*(?:\.\d+)?)\s*(억원|만원|원)", text)
    if not match:
        return None
    amount = float(match.group(1).replace(",", ""))
    multiplier = {"억원": 100_000_000, "만원": 10_000, "원": 1}[match.group(2)]
    return int(amount * multiplier)


def _duration_minutes(text: str) -> int | None:
    hours = _first_int(text, (r"(\d[\d,]*)\s*시간(?:\s*(?:동안|만에))?",))
    minutes = _first_int(text, (r"(\d[\d,]*)\s*분(?:\s*(?:동안|만에))?",))
    if hours is None and minutes is None:
        return None
    return (hours or 0) * 60 + (minutes or 0)


def _fire_cause(text: str) -> dict[str, str]:
    domain_patterns = (
        ("battery", r"(?:리튬\s*)?배터리|축전지|충전\s*중"),
        ("electrical", r"전기(?:적)?\s*(?:요인|원인)|절연열화|누전|합선|단락|아크|전기설비"),
        ("negligence", r"부주의|쓰레기(?:를|를\s*)?\s*(?:소각|태우)|소각\s*중|담뱃불"),
        ("intentional", r"방화|고의로\s*불"),
        ("natural", r"낙뢰|벼락|자연발화"),
        ("mechanical", r"기계(?:적)?\s*(?:요인|결함)|과열|마찰열"),
    )
    domain = next(
        (name for name, pattern in domain_patterns if re.search(pattern, text)),
        "undetermined",
    )
    confirmed = bool(re.search(r"(?:원인|요인)(?:으로|은|이)?\s*(?:확인|밝혀|판명|결론)", text))
    suspected = bool(
        re.search(r"(?:추정|의심|가능성|것으로\s*(?:보고|보며)|불낸\s*듯|번진\s*듯)", text)
    )
    investigating = bool(re.search(r"(?:원인|경위).{0,16}(?:조사|감식)\s*중|조사하고\s*있", text))
    certainty = (
        "confirmed"
        if domain != "undetermined" and confirmed
        else "suspected"
        if domain != "undetermined" and suspected
        else "under_investigation"
        if investigating
        else "unknown"
    )
    legacy_status = (
        "electrical_confirmed"
        if domain in {"electrical", "battery"} and certainty == "confirmed"
        else "electrical_suspected"
        if domain in {"electrical", "battery"} and certainty == "suspected"
        else "unknown"
    )
    return {
        "cause_status": legacy_status,
        "cause_certainty": certainty,
        "cause_domain": domain,
    }


def detect_incident_sentinel(article: Article) -> dict[str, Any]:
    """중대화재·정전 속보를 수치 유무와 무관하게 판정한다."""
    text = _article_text(article)
    fire_text = text
    for phrase in _FIRE_FALSE_POSITIVE_PHRASES:
        fire_text = fire_text.replace(phrase, " ")
    fire_signal = any(signal in fire_text for signal in _FIRE_SIGNALS)
    severity_signal = any(
        signal in fire_text for signal in _FIRE_SEVERITY_SIGNALS if signal != "사상"
    ) or bool(re.search(r"사상(?!\s*(?:최대|최고|처음|첫))", fire_text))
    aggregate_statistics = bool(
        re.search(r"(?:산재|산업재해).{0,24}(?:역대|통계|현황)", fire_text)
        or re.search(r"(?:역대|통계|현황).{0,24}(?:산재|산업재해)", fire_text)
    )
    fire = fire_signal and severity_signal and not aggregate_statistics
    if fire:
        return {
            "matched": True,
            "incident": {
                "incident_type": "fire",
                **_fire_cause(text),
                "incident_status": "breaking",
                "deaths": _first_int(
                    text,
                    (
                        r"사망자?\s*(\d[\d,]*)\s*명",
                        r"(\d[\d,]*)\s*명(?:이|이\s*)?\s*(?:사망|숨져)",
                    ),
                ),
                "injuries": _first_int(
                    text,
                    (
                        r"(?:부상자?|중상자?)\s*(\d[\d,]*)\s*명",
                        r"(\d[\d,]*)\s*명(?:이|이\s*)?\s*(?:부상|중상)",
                    ),
                ),
                "property_damage_krw": _property_damage(text),
                "critical_facility": _critical_facility(text),
            },
        }

    outage = any(signal in text for signal in _OUTAGE_SIGNALS) and any(
        signal in text for signal in _OUTAGE_COMPANION_SIGNALS
    )
    planned = any(signal in text for signal in _PLANNED_OUTAGE_SIGNALS)
    actual = any(signal in text for signal in _ACTUAL_OUTAGE_SIGNALS)
    if outage and not (planned and not actual):
        return {
            "matched": True,
            "incident": {
                "incident_type": "outage",
                "incident_status": "breaking",
                "households": _first_int(
                    text,
                    (
                        r"(\d[\d,]*)\s*(?:여\s*)?(?:세대|가구)",
                        r"(?:세대|가구)\s*(\d[\d,]*)",
                    ),
                ),
                "duration_minutes": _duration_minutes(text),
                "critical_facility": _critical_facility(text),
                "planned": False,
            },
        }

    return {"matched": False, "incident": None}
