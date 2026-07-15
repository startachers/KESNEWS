from __future__ import annotations

import hashlib

from backend.app.services.normalization.title import normalized_article_title
from backend.app.services.normalization.url import canonical_article_url


def make_content_key(
    url: str | None, title: str | None, source: str | None, published_at: str | None
) -> str:
    """content_key 우선순위: canonical URL hash > normalized title+source+date hash (ARCHITECTURE.md 7.1장)."""
    canonical_url = canonical_article_url(url)
    if canonical_url:
        return f"url:{hashlib.sha256(canonical_url.encode('utf-8')).hexdigest()}"
    basis = f"{normalized_article_title(title)}|{source or ''}|{(published_at or '')[:10]}"
    return f"title:{hashlib.sha256(basis.encode('utf-8')).hexdigest()}"
