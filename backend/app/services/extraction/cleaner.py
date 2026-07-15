from __future__ import annotations

import re
from html.parser import HTMLParser


class _TextExtractor(HTMLParser):
    """frontend/js/utils/strings.js cleanText()의 DOMParser textContent 대응 포팅."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []

    def handle_data(self, data: str) -> None:
        self._chunks.append(data)

    @property
    def text(self) -> str:
        return "".join(self._chunks)


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    parser = _TextExtractor()
    parser.feed(str(value))
    parser.close()
    return re.sub(r"\s+", " ", parser.text).strip()


def short_text(value: str | None, max_len: int = 100) -> str:
    text = clean_text(value)
    return f"{text[: max_len - 1]}…" if len(text) > max_len else text
