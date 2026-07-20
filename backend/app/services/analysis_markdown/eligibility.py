from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from backend.app.services.extraction.cleaner import CleaningResult

_NAVIGATION = re.compile(
    r"(?:많이 본 뉴스|실시간 핫뉴스|오늘의 핫 클릭|기사목록|기사 모음|관련기사|"
    r"로그인|회원가입|글자크기|인쇄하기|좋아요|응원해요|후속 원해요|메뉴|AD)", re.I
)
_FACT = re.compile(r"(?:\d|발표|밝혔|말했|따르면|발생|추진|계획|조사|피해|사망|기관|센터)")
_OFFICIAL_DOMAINS = (
    "go.kr", "korea.kr", "assembly.go.kr", "alio.go.kr", "law.go.kr",
    "kesco.or.kr", "kepco.co.kr", "kpx.or.kr",
)


@dataclass(frozen=True)
class EligibilityResult:
    eligible: bool
    reason: str
    source_kind: str


def evaluate(
    cleaning: CleaningResult,
    *,
    status: str,
    url: str,
    config: dict,
) -> EligibilityResult:
    text = cleaning.text.strip()
    host = (urlsplit(url).hostname or "").lower()
    navigation_hits = len(_NAVIGATION.findall(text))
    if not text:
        if "recommendation_section" in cleaning.removed_sections:
            return EligibilityResult(False, "navigation_only", "none")
        return EligibilityResult(False, "selector_failed", "none")
    if cleaning.ai_content_detected and len(text) < 80:
        return EligibilityResult(False, "ai_generated_content_only", "none")
    if navigation_hits >= 4:
        return EligibilityResult(False, "navigation_only", "none")
    if status == "success_summary":
        minimum = int(config["minimum_rss_summary_characters"])
        if len(text) < minimum or not _FACT.search(text):
            return EligibilityResult(False, "body_too_short", "rss_summary")
        return EligibilityResult(True, "", "rss_summary")
    minimum = int(config["minimum_full_text_characters"])
    if any(host == domain or host.endswith(f".{domain}") for domain in _OFFICIAL_DOMAINS):
        minimum = int(config.get("official_document_minimum_characters", minimum))
    if len(text) < minimum:
        return EligibilityResult(False, "body_too_short", "full_text")
    return EligibilityResult(True, "", "full_text")
