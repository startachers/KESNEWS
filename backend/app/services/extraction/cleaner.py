from __future__ import annotations

import re
from dataclasses import dataclass
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


CLEANING_RULE_VERSION = "article-clean-v2.3"

_AI_SECTION_HEADING = re.compile(
    r"(?:핵심요약\s*쏙|쏙\s*AI\s*요약|AI\s*요약|기사\s*AI\s*해설|AI\s*해설|"
    r"Key\s*Points|심층\s*분석|이\s*뉴스는\s*왜\s*나왔나|주요\s*경과|Timeline|"
    r"다각도\s*분석|핵심\s*시사점|향후\s*전망|시나리오별\s*(?:예측|전망)|"
    r"주요\s*용어\s*해설|용어\s*해설|Glossary|출처\s*목록)",
    re.I,
)
_TAIL_SECTION_HEADING = re.compile(
    r"(?:에디터\s*픽|추천기사|관련\s*기사\s*더보기|기자의\s*다른\s*기사|"
    r"많이\s*본\s*뉴스|실시간\s*핫뉴스|오늘의\s*핫\s*클릭|이\s*시각\s*핫클릭|"
    r"랭킹뉴스|최신기사|독자들의\s*PICK|지금\s*많이\s*보는\s*기사|"
    r"한국경제\s*구독신청|AI\s*학습\s*및\s*활용\s*금지|댓글을\s*삭제\s*하시겠습니까|"
    r"댓글\s*내용입력|연속기획\s*더보기\s*버튼|이전\s*콘텐츠)",
    re.I,
)
_DROP_LINE = re.compile(
    r"^(?:닫기|로그인|회원가입|구독|스크랩|공유|댓글|공감\s*버튼|글자\s*크기|"
    r"인쇄(?:하기)?|메뉴\s*(?:열기|닫기)|북마크|뉴스레터\s*가입|AD)$",
    re.I,
)
_LEGAL = re.compile(
    r"(?:ⓒ\s*)?[^.\n]{0,80}(?:무단전재|재배포|AI\s*학습\s*(?:이용|및\s*활용))\s*(?:및\s*)?(?:금지)?",
    re.I,
)
_INLINE_UI = re.compile(
    r"(?:나만의\s*AI\s*비서|구글\s*검색\s*선호\s*추가|알아보기|"
    r"Google\s*검색에서[^.]{0,100}있습니다\.?|사진\s*확대|본문영역|스크롤\s*이동\s*상태바|"
    r"경제\s*기사\s*스크랩\s*기사\s*스크랩\s*댓글\s*공유\s*글자크기\s*조절\s*글자크기\s*프린트\s*프린트|"
    r"[가-힣]{2,4}\s*기자\s*구독하기|구글\s*검색\s*선호\s*출처로\s*추가|"
    r"보기\s*설정\s*닫기\s*글자\s*크기.*?내\s*뉴스플리에\s*저장\s*닫기|"
    r"[가-힣]{2,4}\s*기자\s*구독\s*구독중\s*이전\s*다음\s*이미지\s*확대|"
    r"한국어\s*영어\s*일본어\s*중국어\s*베트남어\s*러시아어\s*독일어\s*불어\s*스페인어|"
    r"로그인\s*회원가입\s*제보|제보\s*입력|댓글\s*\d+|"
    r"가\s*가\s*기사의\s*본문\s*내용은\s*이\s*글자크기로\s*변경됩니다)",
    re.I,
)
_PAGE_UI_TOKEN = (
    r"(?:기사\s*스크랩|댓글|공유|글자\s*크기\s*조절|프린트|상태바|"
    r"구독(?:중)?|이미지\s*확대)"
)
_PAGE_UI_LINE = re.compile(
    rf"^{_PAGE_UI_TOKEN}(?:\s*(?:[·|/]\s*)?{_PAGE_UI_TOKEN})*$",
    re.I,
)
_PHOTO_CAPTION_LINE = re.compile(r"^\s*(?:\[\s*)?사진\s*=\s*[^\]\n]+(?:\s*\])?\s*$", re.I)
_RESALE_DB_TAIL = re.compile(r"(?:ⓒ\s*)?재판매\s*및\s*DB\s*금지", re.I)
_SPACE = re.compile(r"[ \t\u00a0]+")
_AUTOMATIC_TAIL_SECTION = re.compile(
    r"(?:영문기사\s*보기(?:\s*\(View\s+English\s+Article\))?|"
    r"View\s+English\s+Article|이\s*시각\s*주요뉴스|오늘의\s*핫뉴스|"
    r"NEWS\s*많이\s*본\s*기사|많이\s*본\s*기사|다음\s*광고|"
    r"(?:^|\s)▲\s*[^.\n]{0,160}(?:사진(?:제공)?|기자간담회)|"
    r"(?:【|\[)[^】\]\n]{0,60}(?:기자|특파원)[^】\]\n]*(?:】|\]))",
    re.I,
)
_AUTOMATIC_PROFILE_SECTION = re.compile(
    r"[^.\n]{0,100}\bHe\s+is\b|"
    r"\bHe\s+is\.\.\.|(?:기자\s*)?(?:약력|프로필)\b",
    re.I,
)


@dataclass(frozen=True)
class CleaningResult:
    text: str
    noise_detected: bool
    ai_content_detected: bool
    removed_sections: tuple[str, ...]


def _paragraphs(value: str) -> list[str]:
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    chunks = re.split(r"\n+|(?<=[.!?다요])\s{2,}", value)
    return [_SPACE.sub(" ", clean_text(chunk)).strip() for chunk in chunks if clean_text(chunk)]


def clean_article_text(value: str | None, *, title: str = "") -> CleaningResult:
    """문장을 재작성하지 않고 기사 뒤에 붙은 AI/추천/UI 영역과 중복 문단만 제거한다."""
    raw = str(value or "").replace("\x00", "")
    ai_match = _AI_SECTION_HEADING.search(raw)
    tail_match = _TAIL_SECTION_HEADING.search(raw)
    cuts = [match.start() for match in (ai_match, tail_match) if match]
    legal_match = _LEGAL.search(raw)
    if legal_match:
        cuts.append(legal_match.start())
    resale_db_match = _RESALE_DB_TAIL.search(raw)
    if resale_db_match:
        cuts.append(resale_db_match.start())
    working = raw[: min(cuts)] if cuts else raw
    removed: list[str] = []
    if ai_match:
        removed.append("publisher_ai_section")
    if tail_match:
        removed.append("recommendation_section")
    if legal_match or resale_db_match:
        removed.append("copyright_tail")

    paragraphs = _paragraphs(working)
    title_key = clean_text(title)
    seen: set[str] = set()
    kept: list[str] = []
    for paragraph in paragraphs:
        if _PAGE_UI_LINE.fullmatch(paragraph):
            removed.append("page_ui")
            continue
        if _PHOTO_CAPTION_LINE.fullmatch(paragraph):
            removed.append("photo_caption")
            continue
        paragraph = _LEGAL.sub("", paragraph).strip(" ·|")
        paragraph = _INLINE_UI.sub("", paragraph).strip(" ·|")
        if not paragraph or _DROP_LINE.fullmatch(paragraph):
            continue
        if title_key and clean_text(paragraph) == title_key:
            if "title" in seen:
                continue
            seen.add("title")
        duplicate_key = re.sub(r"[\W_]+", "", paragraph).lower()
        if len(duplicate_key) >= 40 and duplicate_key in seen:
            removed.append("duplicate_paragraph")
            continue
        if len(duplicate_key) >= 40:
            seen.add(duplicate_key)
        kept.append(paragraph)
    text = "\n\n".join(kept).strip()
    return CleaningResult(
        text=text,
        noise_detected=bool(
            tail_match
            or _LEGAL.search(raw)
            or resale_db_match
            or _INLINE_UI.search(raw)
            or "page_ui" in removed
            or "photo_caption" in removed
        ),
        ai_content_detected=bool(ai_match),
        removed_sections=tuple(dict.fromkeys(removed)),
    )


def clean_automatic_article_text(
    value: str | None, *, title: str = ""
) -> CleaningResult:
    """자동 수집 본문에만 후행 뉴스·프로필 영역을 추가 제거한다.

    담당자가 확인한 수동 본문은 이 함수를 사용하지 않는다. 일반 기사 문장에 등장한
    단어를 지우지 않도록 충분한 본문 뒤에 나타난 명시적 후행 섹션만 절단한다.
    """
    raw = str(value or "").replace("\x00", "")
    minimum_tail_start = max(120, int(len(raw) * 0.25))
    matches = [
        match
        for pattern in (_AUTOMATIC_TAIL_SECTION, _AUTOMATIC_PROFILE_SECTION)
        if (match := pattern.search(raw)) and match.start() >= minimum_tail_start
    ]
    cut_at = min((match.start() for match in matches), default=None)
    result = clean_article_text(raw[:cut_at] if cut_at is not None else raw, title=title)
    if cut_at is None:
        return result
    return CleaningResult(
        text=result.text,
        noise_detected=True,
        ai_content_detected=result.ai_content_detected,
        removed_sections=tuple(
            dict.fromkeys((*result.removed_sections, "automatic_tail_section"))
        ),
    )
