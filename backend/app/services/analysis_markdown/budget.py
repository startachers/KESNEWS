from __future__ import annotations

import re


def truncate_at_sentence(text: str, limit: int) -> tuple[str, bool]:
    text = text.strip()
    if len(text) <= limit:
        return text, False
    units = re.split(r"(?<=[.!?。])\s+|\n{2,}", text)
    kept: list[str] = []
    length = 0
    for unit in units:
        unit = unit.strip()
        if not unit:
            continue
        extra = len(unit) + (2 if kept else 0)
        if length + extra > limit:
            break
        kept.append(unit)
        length += extra
    if not kept:
        boundary = max(text.rfind(mark, 0, limit) for mark in (". ", "다. ", "? ", "! "))
        if boundary < max(80, limit // 3):
            # 첫 문장이 예산보다 길더라도 문장 중간을 자르거나 기사를 조용히
            # 누락시키지 않는다. 문서 예산 단계가 비필수 기사 제외 또는 명시적
            # 오류로 처리한다.
            first = next((unit.strip() for unit in units if unit.strip()), text)
            return first, True
        return text[: boundary + 1].rstrip(), True
    return "\n\n".join(kept), True


def apply_article_limits(articles: list[dict], config: dict) -> None:
    limits = config["article_character_limits"]
    for article in articles:
        limit = int(limits.get(article.get("priority") or "reference", limits["reference"]))
        included, reduced = truncate_at_sentence(article["cleanedText"], limit)
        article["includedText"] = included
        article["includedCharacterCount"] = len(included)
        article["truncated"] = reduced
