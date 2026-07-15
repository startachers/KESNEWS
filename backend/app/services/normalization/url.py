from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit

_TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "ref", "source"}


def safe_url(value: str | None) -> str:
    if not value:
        return ""
    try:
        parts = urlsplit(str(value))
    except ValueError:
        return ""
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return ""
    return str(value)


def canonical_article_url(value: str | None) -> str:
    safe = safe_url(value)
    if not safe:
        return ""
    try:
        parts = urlsplit(safe)
        hostname = (parts.hostname or "").lower()
        if "news.google.com" in hostname:
            return ""
        host = hostname[4:] if hostname.startswith("www.") else hostname
        path = parts.path.rstrip("/")
        query_pairs = [
            (key, val) for key, val in parse_qsl(parts.query, keep_blank_values=True) if key not in _TRACKING_PARAMS
        ]
        query = f"?{urlencode(query_pairs)}" if query_pairs else ""
        return f"{host}{path}{query}".lower()
    except ValueError:
        return ""
