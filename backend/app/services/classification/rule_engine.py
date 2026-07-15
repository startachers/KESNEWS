from __future__ import annotations

from typing import Any

_CATEGORY_RULES: list[tuple[str, list[str]]] = [
    ("safety", ["화재", "감전", "사고", "안전점검", "누전", "정전", "재해"]),
    ("management", ["사장", "감사", "국정감사", "경영평가", "인사", "채용", "노조", "비위"]),
    ("policy", ["산업통상", "전기안전관리법", "정책", "규제", "법안", "국회"]),
    ("industry", ["태양광", "ess", "전기차", "배터리", "신재생", "충전시설"]),
    ("community", ["협약", "봉사", "지원", "캠페인", "지역", "상생"]),
]


def infer_category(article: dict[str, Any]) -> str:
    text = f"{article.get('title') or ''} {article.get('description') or ''}".lower()
    for category, keywords in _CATEGORY_RULES:
        if any(keyword in text for keyword in keywords):
            return category
    return "direct"


def should_exclude(article: dict[str, Any], exclude_keywords: list[str]) -> bool:
    text = f"{article.get('title') or ''} {article.get('description') or ''}".lower()
    return any(keyword.strip() and keyword.strip().lower() in text for keyword in exclude_keywords)
