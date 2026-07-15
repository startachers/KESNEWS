from __future__ import annotations

import re
import unicodedata

from backend.app.services.extraction.cleaner import clean_text

_LEADING_BRACKET = re.compile(r"^\s*[\[【(][^\]】)]{1,18}[\]】)]\s*")
_TRAILING_SOURCE = re.compile(r"\s*[-–—]\s*[^-–—]{2,24}$")
_NON_ALNUM_KO = re.compile(r"[^가-힣a-z0-9]")


def normalized_article_title(value: str | None) -> str:
    text = unicodedata.normalize("NFKC", clean_text(value or "")).lower()
    text = _LEADING_BRACKET.sub("", text)
    text = _TRAILING_SOURCE.sub("", text)
    text = _NON_ALNUM_KO.sub("", text)
    return text[:180]
