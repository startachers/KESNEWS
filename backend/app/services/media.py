from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

TRUSTED_MEDIA_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "trusted_media.yaml"


@dataclass(frozen=True)
class PublisherDecision:
    publisher_id: str | None
    allowed: bool
    reason: str
    hostname: str


def normalize_hostname(raw_url: str) -> str:
    try:
        return (urlsplit(str(raw_url or "")).hostname or "").lower().removeprefix("www.")
    except ValueError:
        return ""


def domain_matches(hostname: str, allowed: str) -> bool:
    normalized = allowed.lower().removeprefix("www.").strip()
    return bool(normalized) and (
        hostname == normalized or hostname.endswith(f".{normalized}")
    )


def _parse_inline_media(value: str) -> dict[str, Any] | None:
    match = re.match(r"^\{(.*)\}$", value.strip())
    if not match:
        return None
    body = match.group(1)
    id_match = re.search(r"(?:^|,)\s*id:\s*([^,}\s]+)", body)
    name_match = re.search(r"(?:^|,)\s*name:\s*([^,}]+)", body)
    domains_match = re.search(r"(?:^|,)\s*domains:\s*\[([^]]*)\]", body)
    if not id_match or not domains_match:
        return None

    def unquote(raw: str) -> str:
        return raw.strip().strip("'").strip(chr(34))

    return {
        "id": unquote(id_match.group(1)),
        "name": unquote(name_match.group(1)) if name_match else "",
        "domains": [
            unquote(part)
            for part in domains_match.group(1).split(",")
            if part.strip()
        ],
    }


def load_trusted_media_config(path: Path | None = None) -> dict[str, Any]:
    """현재 설정 파일의 목록/인라인 매핑만 읽는다. 새 YAML 운영 의존성은 두지 않는다."""
    config_path = path or TRUSTED_MEDIA_CONFIG_PATH
    raw = config_path.read_text(encoding="utf-8")
    result: dict[str, Any] = {
        "trusted_media": [],
        "approved_incident_media": [],
        "official_source_exemptions": [],
        "incident_official_sources": [],
    }
    current = ""
    supported = set(result)
    for original_line in raw.splitlines():
        line = original_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        section_match = re.match(r"^([a-z_]+):\s*(.*)$", line)
        if section_match and not line.startswith((" ", "\t")):
            current = section_match.group(1) if section_match.group(1) in supported else ""
            continue
        item_match = re.match(r"^\s+-\s+(.+)$", line)
        if not current or not item_match:
            continue
        value = item_match.group(1).strip()
        if current in {"trusted_media", "approved_incident_media"}:
            parsed = _parse_inline_media(value)
            if parsed:
                result[current].append(parsed)
        else:
            result[current].append(value.strip().strip("'").strip(chr(34)))
    if not result["trusted_media"]:
        raise ValueError(f"신뢰 언론사 설정이 비어 있습니다: {config_path}")
    return result


def _publisher_url(article: dict[str, Any]) -> str:
    provider = str(article.get("provider") or "")
    if provider == "연합뉴스 RSS":
        return "https://yna.co.kr"
    if provider == "Google 뉴스 RSS":
        return str(article.get("sourceUrl") or "")
    if provider == "네이버 뉴스 API":
        return str(article.get("originalLink") or "")
    return str(article.get("url") or "")


def identify_trusted_publisher(
    article: dict[str, Any],
    *,
    config: dict[str, Any] | None = None,
    incident_matched: bool = False,
) -> PublisherDecision:
    config = config or load_trusted_media_config()
    hostname = normalize_hostname(_publisher_url(article))
    if not hostname:
        return PublisherDecision(None, False, "unknown_publisher", "")

    for domain in config["official_source_exemptions"]:
        if domain_matches(hostname, domain):
            return PublisherDecision(f"official:{domain}", True, "official_source", hostname)
    for domain in config["incident_official_sources"]:
        if domain_matches(hostname, domain):
            return PublisherDecision(f"official:{domain}", True, "official_source", hostname)
    for medium in config["trusted_media"]:
        if any(domain_matches(hostname, domain) for domain in medium["domains"]):
            return PublisherDecision(str(medium["id"]), True, "trusted_media", hostname)
    if incident_matched:
        for medium in config["approved_incident_media"]:
            if any(domain_matches(hostname, domain) for domain in medium["domains"]):
                return PublisherDecision(str(medium["id"]), True, "trusted_media", hostname)
    return PublisherDecision(None, False, "untrusted_media", hostname)


def is_yonhap_article(article: dict[str, Any]) -> bool:
    """dedup(article_preference)과 classification(relevance_sort) 양쪽에서 쓰여 순환 import를 피하려고 별도 모듈에 둔다."""
    if str(article.get("source") or "").strip() == "연합뉴스" or str(article.get("provider") or "").strip() == "연합뉴스":
        return True
    try:
        hostname = (urlsplit(str(article.get("url") or "")).hostname or "").lower()
        return hostname == "yna.co.kr" or hostname.endswith(".yna.co.kr")
    except ValueError:
        return False
