from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urljoin

from backend.app.services.media import domain_matches, load_trusted_media_config, normalize_hostname


ERROR_MESSAGES = {
    "body_truncated": "기사 본문 또는 요약이 문장 중간에서 잘렸습니다.",
    "body_contaminated": "기사 본문 뒤에 추천기사 또는 다른 기사 내용이 포함돼 있습니다.",
    "body_unavailable": "AI 분석에 사용할 기사 본문을 확보하지 못했습니다.",
    "publisher_identity_mismatch": "표시된 언론사와 실제 원문 발행사가 일치하지 않습니다.",
    "canonical_url_unresolved": "실제 기사 원문 주소를 확인하지 못했습니다.",
    "ai_generated_content_remains": "언론사 AI 해설 또는 AI 생성 콘텐츠가 정제 본문에 남아 있습니다.",
}

API_CODE_BY_ERROR = {
    "body_truncated": "ARTICLE_BODY_TRUNCATED",
    "body_contaminated": "ARTICLE_BODY_CONTAMINATED",
    "body_unavailable": "ARTICLE_BODY_UNAVAILABLE",
    "publisher_identity_mismatch": "ARTICLE_PUBLISHER_MISMATCH",
    "canonical_url_unresolved": "ARTICLE_CANONICAL_URL_UNRESOLVED",
    "ai_generated_content_remains": "ARTICLE_AI_CONTENT_REMAINS",
}

_ELLIPSIS_END = re.compile(r"(?:\.{3,}|…+)\s*[\"'’”)]*$")
_COMPLETE_END = re.compile(r"(?:[.!?]|(?:다|요|임|됨|함))[\"'’”)]*$")
_RESIDUAL_CONTAMINATION = re.compile(
    r"(?:많이\s*본\s*(?:기사|뉴스)|이\s*시각\s*주요기사|HOT\s*뉴스|랭킹뉴스|"
    r"인기\s*기사|추천기사|기자의\s*다른\s*기사|다른\s*기사\s*어떠세요|"
    r"뉴스룸\s*PICK|오늘의\s*주요기사|Your browser does not support the audio element|"
    r"오피니언|최신기사)", re.I
)
_RESIDUAL_AI = re.compile(
    r"(?:기사\s*AI\s*해설|AI\s*해설|AI\s*요약|시나리오별\s*(?:예측|전망)|Key\s*Points)", re.I
)
_GOOGLE_HOSTS = {"news.google.com", "news.google.co.kr"}


@dataclass(frozen=True)
class SourceValidation:
    source: str
    raw_source: str
    resolved_url: str
    canonical_url: str
    source_domain: str
    page_publisher: str
    normalization_reason: str
    errors: tuple[str, ...]


def _publisher_for_domain(hostname: str) -> dict | None:
    if not hostname:
        return None
    config = load_trusted_media_config()
    for medium in [*config["trusted_media"], *config["approved_incident_media"]]:
        if any(domain_matches(hostname, domain) for domain in medium["domains"]):
            return medium
    return None


def _publisher_for_name(value: str) -> dict | None:
    key = re.sub(r"[^0-9a-z가-힣]", "", str(value or "").lower())
    if not key:
        return None
    config = load_trusted_media_config()
    for medium in [*config["trusted_media"], *config["approved_incident_media"]]:
        candidates = [medium["id"], medium.get("name") or "", *medium["domains"]]
        if any(re.sub(r"[^0-9a-z가-힣]", "", item.lower()) == key for item in candidates):
            return medium
    return None


def validate_source(
    *, raw_source: str, displayed_source: str, source_url: str,
    resolved_url: str = "", canonical_url: str = "", page_publisher: str = "",
) -> SourceValidation:
    resolved = resolved_url or source_url or ""
    canonical = urljoin(resolved, canonical_url) if canonical_url else ""
    final_url = canonical or resolved
    host = normalize_hostname(final_url)
    resolved_host = normalize_hostname(resolved)
    canonical_host = normalize_hostname(canonical)
    errors: list[str] = []
    if not host or host in _GOOGLE_HOSTS:
        errors.append("canonical_url_unresolved")

    domain_publisher = _publisher_for_domain(host)
    resolved_publisher = _publisher_for_domain(resolved_host)
    canonical_publisher = _publisher_for_domain(canonical_host)
    page_identity = _publisher_for_name(page_publisher)
    displayed_identity = _publisher_for_name(displayed_source or raw_source)
    if domain_publisher and page_identity and domain_publisher["id"] != page_identity["id"]:
        errors.append("publisher_identity_mismatch")
    if (
        resolved_publisher and canonical_publisher
        and resolved_publisher["id"] != canonical_publisher["id"]
    ):
        errors.append("publisher_identity_mismatch")

    final_source = displayed_source or raw_source or ""
    reason = "raw_source"
    if domain_publisher and (not page_identity or page_identity["id"] == domain_publisher["id"]):
        final_source = page_identity.get("name") if page_identity else domain_publisher.get("name")
        reason = "resolved_domain_and_page_publisher" if page_identity else "verified_domain_mapping"
    elif page_identity and not domain_publisher:
        final_source = page_identity.get("name") or final_source
        reason = "page_publisher"
    elif domain_publisher and displayed_identity and domain_publisher["id"] != displayed_identity["id"]:
        # URL 도메인이 신뢰 매핑으로 명확하면 수집 당시 표시값을 보존하고 실제 발행사로 정상화한다.
        final_source = domain_publisher.get("name") or final_source
        reason = "verified_domain_mapping"

    return SourceValidation(
        source=final_source or "", raw_source=raw_source or displayed_source or "",
        resolved_url=resolved, canonical_url=canonical, source_domain=host,
        page_publisher=page_publisher or "", normalization_reason=reason,
        errors=tuple(dict.fromkeys(errors)),
    )


def body_errors(text: str, *, status: str) -> tuple[str, ...]:
    value = (text or "").strip()
    errors: list[str] = []
    if not value or status in {"failed", "missing", "not_attempted"}:
        errors.append("body_unavailable")
        return tuple(errors)
    if (
        _ELLIPSIS_END.search(value)
        or value.count("(") > value.count(")")
        or value.count("[") > value.count("]")
        or value.count("“") > value.count("”")
        or value.count('"') % 2 == 1
        or not _COMPLETE_END.search(value)
    ):
        errors.append("body_truncated")
    if _RESIDUAL_CONTAMINATION.search(value):
        errors.append("body_contaminated")
    if _RESIDUAL_AI.search(value):
        errors.append("ai_generated_content_remains")
    return tuple(dict.fromkeys(errors))


def serialize_errors(errors: list[str] | tuple[str, ...]) -> list[dict[str, str]]:
    return [
        {"code": API_CODE_BY_ERROR[item], "status": item, "message": ERROR_MESSAGES[item]}
        for item in errors if item in ERROR_MESSAGES
    ]
