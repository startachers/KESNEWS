from __future__ import annotations

import json
import re
import sqlite3
from typing import Any
from urllib.parse import urlsplit

from backend.app.services.analysis_markdown.config import load_config
from backend.app.services.analysis_markdown.eligibility import evaluate
from backend.app.services.analysis_markdown.quality import publisher_statistics
from backend.app.services.extraction.cleaner import CleaningResult, clean_article_text
from backend.app.services.extraction.evidence_validation import body_errors

_SENTENCE_END = re.compile(r"(?:[.!?]|(?:다|요|임|됨|함))(?:(?:[\"'’”)]*)\s|$)")
_OFFICIAL_DOMAINS = (
    "go.kr", "korea.kr", "assembly.go.kr", "alio.go.kr", "law.go.kr",
    "kesco.or.kr", "kepco.co.kr", "kpx.or.kr",
)


def _official(url: str) -> bool:
    host = (urlsplit(url or "").hostname or "").lower()
    return any(host == domain or host.endswith(f".{domain}") for domain in _OFFICIAL_DOMAINS)


def assess(
    article: dict[str, Any], cleaning: CleaningResult, *, status: str, method: str,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    text = cleaning.text.strip()
    sentences = len(_SENTENCE_END.findall(text))
    flags = list(cleaning.removed_sections)
    if cleaning.noise_detected:
        flags.append("page_noise")
    if cleaning.ai_content_detected:
        flags.append("publisher_ai_content")
    incomplete = bool(text and not re.search(r"[.!?다요임됨함][\"'’”)]*$", text))
    if incomplete:
        flags.append("incomplete_ending")
    flags = list(dict.fromkeys(flags))

    score = 0
    reasons: list[str] = []
    if status == "success_full":
        score += 50
        reasons.append("전문 확보")
    elif status == "success_summary":
        score += 62
        reasons.append("유효 RSS 요약")
    elif status == "not_attempted":
        reasons.append("본문 추출 전")
    else:
        reasons.append("본문 추출 실패")
    score += min(15, len(text) // 50)
    score += min(15, sentences * 3)
    if article.get("source"):
        score += 3
    else:
        reasons.append("언론사 확인 불가")
    if article.get("pubDate") or article.get("publishedAt"):
        score += 2
    else:
        reasons.append("보도 시각 확인 불가")
    if _official(article.get("url") or ""):
        score += 8
        reasons.append("공식자료 출처")
    if method in {"json_ld", "publisher_selector", "stored_body", "article_page"}:
        score += 5
    if cleaning.noise_detected:
        reasons.append("페이지 부가 콘텐츠 제거")
    if cleaning.ai_content_detected:
        reasons.append("언론사 AI 콘텐츠 감지")
    if incomplete:
        score -= 15
        reasons.append("문장 종료 불완전")
    if sentences < 2 and status != "failed":
        score -= 10
        reasons.append("완전한 문장 부족")
    if article.get("publisherAllowed") is False:
        score = min(score, 59)
        reasons.append("신뢰 언론사 허용목록 제외")
    score = max(0, min(100, score))
    absolute_errors = list(dict.fromkeys([
        *body_errors(text, status=status),
        *(article.get("sourceValidationErrors") or []),
    ]))
    grade = "excellent" if score >= 90 else "good" if score >= 75 else "limited" if score >= 60 else "unavailable"
    base = evaluate(cleaning, status=status, url=article.get("url") or "", config=config)
    eligible = bool(
        base.eligible
        and not absolute_errors
        and article.get("source")
        and (article.get("pubDate") or article.get("publishedAt"))
        and article.get("publisherAllowed") is not False
    )
    if not eligible and base.reason and base.reason not in reasons:
        reasons.append(base.reason)
    if absolute_errors:
        grade = "unavailable"
        score = min(score, 59)
    return {
        "extractionStatus": status,
        "contentQualityScore": score,
        "qualityGrade": grade,
        "analysisEligible": eligible,
        "representativeSelectable": eligible,
        "qualityReasons": list(dict.fromkeys(reasons)),
        "rawCharacterCount": len(article.get("rawText") or article.get("bodyText") or ""),
        "cleanedCharacterCount": len(text),
        "completeSentenceCount": sentences,
        "contaminationFlags": flags,
        "extractionMethod": method,
        "validationErrors": absolute_errors,
    }


def latest_for_article(connection: sqlite3.Connection, article_id: str) -> dict[str, Any] | None:
    row = connection.execute(
        "SELECT * FROM article_extractions WHERE article_id = ? ORDER BY created_at DESC LIMIT 1",
        (article_id,),
    ).fetchone()
    if row is None:
        return None
    keys = set(row.keys())
    return {
        "extractionId": row["id"],
        "extractionStatus": row["extraction_status"],
        "contentQualityScore": row["content_quality_score"] if "content_quality_score" in keys else None,
        "qualityGrade": row["quality_grade"] if "quality_grade" in keys else None,
        "analysisEligible": bool(row["analysis_eligible"]),
        "representativeSelectable": bool(row["analysis_eligible"]),
        "qualityReasons": json.loads(row["quality_reasons_json"] or "[]") if "quality_reasons_json" in keys else ([row["failure_reason"]] if row["failure_reason"] else []),
        "rawCharacterCount": row["raw_character_count"],
        "cleanedCharacterCount": row["cleaned_character_count"],
        "completeSentenceCount": row["complete_sentence_count"] if "complete_sentence_count" in keys else 0,
        "contaminationFlags": json.loads(row["contamination_flags_json"] or "[]") if "contamination_flags_json" in keys else [],
        "lastExtractedAt": row["created_at"],
        "extractionMethod": (row["extraction_method"] if "extraction_method" in keys else None) or "legacy",
        "cleanedText": row["cleaned_text"] or "",
        "canonicalUrl": row["canonical_url"] if "canonical_url" in keys else "",
        "pagePublisher": row["page_publisher"] if "page_publisher" in keys else "",
        "sourceDomain": row["source_domain"] if "source_domain" in keys else "",
        "rawSource": row["raw_source"] if "raw_source" in keys else "",
        "normalizedSource": row["normalized_source"] if "normalized_source" in keys else "",
        "normalizationReason": row["normalization_reason"] if "normalization_reason" in keys else "",
        "validationErrors": json.loads(row["validation_errors_json"] or "[]") if "validation_errors_json" in keys else [],
    }


def quality_for_article(connection: sqlite3.Connection, article: dict[str, Any]) -> dict[str, Any]:
    latest = latest_for_article(connection, article["id"])
    if latest and latest.get("contentQualityScore") is not None:
        # 추출 이력은 당시 판정을 보존하되, 화면과 대표 선정은 현재 정책으로 다시 평가한다.
        # 정제 완료된 부가 콘텐츠 때문에 과거 점수가 낮았던 기사도 실제 정제 본문으로 판정한다.
        cleaning = clean_article_text(latest.get("cleanedText") or "", title=article.get("title") or "")
        current = assess(
            {**article, "rawText": latest.get("cleanedText") or "", "sourceValidationErrors": latest.get("validationErrors") or []}, cleaning,
            status=latest["extractionStatus"], method=latest.get("extractionMethod") or "legacy",
        )
        current["rawCharacterCount"] = latest["rawCharacterCount"]
        current["contaminationFlags"] = list(dict.fromkeys([
            *(latest.get("contaminationFlags") or []),
            *(current.get("contaminationFlags") or []),
        ]))
        current["qualityReasons"] = list(dict.fromkeys([
            *(current.get("qualityReasons") or []),
            *(latest.get("qualityReasons") or []),
        ]))
        return _apply_publisher_status(
            connection, article, {**latest, **current, "cleanedText": cleaning.text}
        )
    if latest:
        cleaning = clean_article_text(latest.get("cleanedText") or "", title=article.get("title") or "")
        derived = assess(
            {**article, "rawText": latest.get("cleanedText") or "", "sourceValidationErrors": latest.get("validationErrors") or []}, cleaning,
            status=latest["extractionStatus"], method=latest.get("extractionMethod") or "legacy",
        )
        return _apply_publisher_status(connection, article, {**latest, **derived})
    status = "success_full" if article.get("bodyText") else "not_attempted"
    raw = article.get("bodyText") or ""
    cleaning = clean_article_text(raw, title=article.get("title") or "")
    derived = assess({**article, "rawText": raw}, cleaning, status=status, method="stored_body" if raw else "none")
    return _apply_publisher_status(
        connection,
        article,
        {**derived, "lastExtractedAt": article.get("bodyFetchedAt"), "cleanedText": cleaning.text},
    )


def _apply_publisher_status(
    connection: sqlite3.Connection,
    article: dict[str, Any],
    quality: dict[str, Any],
) -> dict[str, Any]:
    config = load_config()
    publisher = article.get("publisherId") or article.get("source")
    blocked = set(config.get("disabled_publishers") or [])
    blocked.update(
        item["publisherId"]
        for item in publisher_statistics(connection, config)
        if item["status"] in {"quarantine", "disabled"}
    )
    if not publisher or publisher not in blocked:
        return quality
    reasons = list(quality.get("qualityReasons") or [])
    if "언론사 상태가 분석 제외입니다" not in reasons:
        reasons.append("언론사 상태가 분석 제외입니다")
    return {
        **quality,
        "contentQualityScore": min(int(quality.get("contentQualityScore") or 0), 59),
        "qualityGrade": "unavailable",
        "analysisEligible": False,
        "representativeSelectable": False,
        "qualityReasons": reasons,
    }
