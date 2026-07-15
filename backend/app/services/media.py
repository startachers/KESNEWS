from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit


def is_yonhap_article(article: dict[str, Any]) -> bool:
    """dedup(article_preference)과 classification(relevance_sort) 양쪽에서 쓰여 순환 import를 피하려고 별도 모듈에 둔다."""
    if str(article.get("source") or "").strip() == "연합뉴스" or str(article.get("provider") or "").strip() == "연합뉴스":
        return True
    try:
        hostname = (urlsplit(str(article.get("url") or "")).hostname or "").lower()
        return hostname == "yna.co.kr" or hostname.endswith(".yna.co.kr")
    except ValueError:
        return False
