from __future__ import annotations

import re
import unicodedata
from functools import cmp_to_key
from typing import Any

from backend.app.core.clock import now_iso
from backend.app.services.classification.rule_engine import infer_category  # noqa: F401  (재수출)
from backend.app.services.extraction.cleaner import clean_text
from backend.app.services.ids import make_id
from backend.app.services.media import is_yonhap_article
from backend.app.services.normalization.dates import date_value

Article = dict[str, Any]

CLASSIFIER_VERSION = "phase3-rules-v1"

_HEAVY_WEIGHTS = {
    "사망": 6,
    "중대재해": 6,
    "압수수색": 6,
    "고발": 5,
    "해킹": 5,
    "감전": 4,
    "화재": 4,
    "사고": 3,
    "논란": 3,
    "위반": 3,
    "부실": 3,
    "정전": 3,
    "피해": 3,
    "국정감사": 2,
    "감사": 2,
    "징계": 4,
}


def classify_article(raw: Article, risk_keywords: list[str], positive_keywords: list[str]) -> Article:
    title_text = str(raw.get("title") or "")
    text = f"{title_text} {raw.get('description') or ''}".lower()
    title = title_text.lower()
    score = 0
    matched: list[str] = []
    for keyword in risk_keywords:
        key = keyword.strip()
        if not key or key.lower() not in text:
            continue
        matched.append(key)
        score += _HEAVY_WEIGHTS.get(key, 2)
        if key.lower() in title:
            score += 1
    positives = [k for k in positive_keywords if k.strip() and k.strip().lower() in text]
    for keyword in positives:
        if keyword not in matched:
            matched.append(keyword)
    risk = "critical" if score >= 6 else "watch" if score >= 3 else "routine"
    sentiment = "negative" if score >= 3 else "positive" if positives else "neutral"
    included = raw["included"] if raw.get("included") is not None else bool(raw.get("manual"))
    return {
        **raw,
        "id": raw.get("id") or make_id(),
        "pubDate": raw.get("pubDate") or now_iso(),
        "description": clean_text(raw.get("description") or ""),
        "matchedKeywords": matched[:8],
        "risk": risk,
        "riskScore": score,
        "sentiment": sentiment,
        "included": included,
        "starred": bool(raw.get("starred")),
        "note": raw.get("note") or "",
        "manual": bool(raw.get("manual")),
        "isDemo": bool(raw.get("isDemo")),
    }


def get_relevance(article: Article) -> dict[str, Any]:
    def normalize(value: str | None) -> str:
        return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", clean_text(value or "")).lower())

    title = normalize(article.get("title"))
    full_text = f"{title} {normalize(article.get('description'))}"

    def has_agency(text: str) -> bool:
        return bool(re.search(r"한국전기안전공사|전기안전공사", text))

    def has_electric_fire(text: str) -> bool:
        return bool(re.search(r"전기[\s·ㆍ-]*화재", text))

    def has_electrocution(text: str) -> bool:
        return bool(re.search(r"감전[\s·ㆍ-]*사고", text))

    def has_ministry_energy(text: str) -> bool:
        if "기후에너지환경부" not in text:
            return False
        context = text.replace("기후에너지환경부", " ")
        return bool(re.search(r"에너지|전기", context))

    def has_renewable(text: str) -> bool:
        return bool(re.search(r"재생[\s·ㆍ-]*에너지", text))

    criteria = [
        (1, "① 공사 직접 거론", has_agency),
        (2, "② 전기화재", has_electric_fire),
        (3, "③ 감전사고", has_electrocution),
        (4, "④ 기후에너지환경부+에너지/전기", has_ministry_energy),
        (5, "⑤ 재생에너지", has_renewable),
    ]
    matches = [(rank, reason, match) for rank, reason, match in criteria if match(full_text)]
    if not matches:
        return {
            "rank": 99,
            "score": 0,
            "label": "낮음",
            "titleMatch": False,
            "matchCount": 0,
            "reasons": ["지정 관련도 기준 미일치"],
        }
    primary_rank, _, primary_match = matches[0]
    title_match = primary_match(title)
    base_score = {1: 100, 2: 85, 3: 70, 4: 55, 5: 40}[primary_rank]
    score = (
        100
        if primary_rank == 1
        else min(99, base_score + (7 if title_match else 0) + min(5, (len(matches) - 1) * 2))
    )
    label = "매우 높음" if primary_rank == 1 else "높음" if primary_rank <= 3 else "보통" if primary_rank == 4 else "관심"
    return {
        "rank": primary_rank,
        "score": score,
        "label": label,
        "titleMatch": title_match,
        "matchCount": len(matches),
        "reasons": [reason for _, reason, _ in matches],
    }


def _relevance_compare(a: Article, b: Article) -> int:
    left = get_relevance(a)
    right = get_relevance(b)
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
    title_cmp = _ko_compare(str(a.get("title") or ""), str(b.get("title") or ""))
    if title_cmp:
        return title_cmp
    return _ko_compare(str(a.get("id") or ""), str(b.get("id") or ""))


def _ko_compare(a: str, b: str) -> int:
    return -1 if a < b else 1 if a > b else 0


relevance_sort_key = cmp_to_key(_relevance_compare)
