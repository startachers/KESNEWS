from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit


# 기사 한 건이 아니라 언론사 DOM 계열에 적용되는 선택자 힌트다. 표준 라이브러리
# HTMLParser에서 id/class/itemprop을 판정하므로 CSS selector의 핵심 토큰만 관리한다.
PUBLISHER_CONTENT_HINTS: dict[str, tuple[str, ...]] = {
    "news.kbs.co.kr": ("news-view-content", "detail-body", "comp-box"),
    "ytn.co.kr": ("article", "article-text", "content"),
    "mk.co.kr": ("news_cnt_detail_wrap", "article_body", "art_txt"),
    "busan.com": ("article_content", "news_content", "view_content"),
    "yna.co.kr": ("story-news", "article", "article-body"),
    "news1.kr": ("article_body", "detail", "article-content"),
}


def publisher_hints(url: str) -> tuple[str, ...]:
    hostname = (urlsplit(url).hostname or "").lower()
    for domain, hints in PUBLISHER_CONTENT_HINTS.items():
        if hostname == domain or hostname.endswith(f".{domain}"):
            return hints
    return ()


def alternate_urls(url: str) -> list[tuple[str, str]]:
    """원문 다음에 시도할 보수적인 모바일/AMP/인쇄 URL 후보를 만든다."""
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return []
    candidates: list[tuple[str, str]] = []
    host = parsed.hostname.lower()
    if not host.startswith("m.") and host not in {"news.kbs.co.kr"}:
        mobile_host = f"m.{host}"
        candidates.append(("mobile", urlunsplit(parsed._replace(netloc=mobile_host))))
    path = parsed.path.rstrip("/")
    if not re.search(r"(?:/amp|\.amp)$", path, re.I):
        candidates.append(("amp", urlunsplit(parsed._replace(path=f"{path}/amp"))))
    query = parsed.query
    print_query = f"{query}&output=1" if query else "output=1"
    candidates.append(("print", urlunsplit(parsed._replace(query=print_query))))
    seen = {url}
    return [(kind, value) for kind, value in candidates if not (value in seen or seen.add(value))]
