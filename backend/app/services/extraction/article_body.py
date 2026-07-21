from __future__ import annotations

import ipaddress
import base64
import html as html_lib
import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Callable

from backend.app.services.extraction.cleaner import clean_text
from backend.app.services.extraction.publisher_extractors import alternate_urls, publisher_hints

MAX_RESPONSE_BYTES = 3 * 1024 * 1024
MIN_BODY_LENGTH = 200
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) KESCO-Briefing/1.0"
GOOGLE_NEWS_BATCH_URL = (
    "https://news.google.com/_/DotsSplashUi/data/batchexecute?rpcids=Fbv4je"
)

_CONTENT_HINT = re.compile(r"(?:article|news|content|view|read|story|본문|뉴스본문)", re.I)
_EXCLUDE_HINT = re.compile(
    r"(?:nav|menu|header|footer|aside|comment|reply|related|recommend|advert|\bad\b|banner|share)",
    re.I,
)


@dataclass(frozen=True)
class BodyFetchResult:
    body_text: str
    status: str
    error: str = ""
    resolved_url: str = ""
    attempts: tuple[dict[str, str], ...] = ()
    canonical_url: str = ""
    page_publisher: str = ""


class _ArticleParser(HTMLParser):
    def __init__(self, content_hints: tuple[str, ...] = ()) -> None:
        super().__init__(convert_charrefs=True)
        self._stack: list[tuple[bool, bool]] = []
        self._paragraph_depths: list[int] = []
        self._script_type = ""
        self._script_chunks: list[str] = []
        self.candidate_chunks: list[str] = []
        self.paragraphs: list[str] = []
        self.json_ld: list[str] = []
        self.meta_descriptions: list[str] = []
        self.site_names: list[str] = []
        self.canonical_url = ""
        self._publisher_hint = re.compile(
            "|".join(re.escape(item) for item in content_hints), re.I
        ) if content_hints else None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = " ".join(value or "" for key, value in attrs if key in {"id", "class", "itemprop"})
        parent_candidate = self._stack[-1][0] if self._stack else False
        parent_excluded = self._stack[-1][1] if self._stack else False
        excluded = parent_excluded or tag in {
            "nav", "header", "footer", "aside", "form", "script", "style", "noscript",
        } or bool(
            _EXCLUDE_HINT.search(attr)
        )
        candidate = not excluded and (
            parent_candidate or tag in {"article", "main"} or bool(_CONTENT_HINT.search(attr))
            or bool(self._publisher_hint and self._publisher_hint.search(attr))
        )
        self._stack.append((candidate, excluded))
        if tag == "p" and not excluded:
            self._paragraph_depths.append(len(self._stack))
            self.paragraphs.append("")
        if tag == "script":
            attrs_dict = dict(attrs)
            self._script_type = (attrs_dict.get("type") or "").lower()
            self._script_chunks = []
        attrs_dict = dict(attrs)
        if tag == "meta":
            key = (attrs_dict.get("property") or attrs_dict.get("name") or "").lower()
            if key in {"og:description", "description"} and attrs_dict.get("content"):
                self.meta_descriptions.append(attrs_dict["content"] or "")
            if key == "og:site_name" and attrs_dict.get("content"):
                self.site_names.append(attrs_dict["content"] or "")
        if tag == "link" and (attrs_dict.get("rel") or "").lower() == "canonical":
            self.canonical_url = attrs_dict.get("href") or ""
        if tag in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}:
            self._stack.pop()

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and "ld+json" in self._script_type:
            self.json_ld.append("".join(self._script_chunks))
        if tag == "script":
            self._script_type = ""
            self._script_chunks = []
        if tag == "p" and self._paragraph_depths:
            self._paragraph_depths.pop()
        if self._stack:
            self._stack.pop()

    def handle_data(self, data: str) -> None:
        if self._script_type:
            self._script_chunks.append(data)
            return
        if not self._stack or self._stack[-1][1]:
            return
        if self._stack[-1][0]:
            self.candidate_chunks.append(data)
        if self._paragraph_depths and self.paragraphs:
            self.paragraphs[-1] += data


class _GoogleNewsParamsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.data_p = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "c-wiz" and not self.data_p:
            self.data_p = dict(attrs).get("data-p") or ""


def _article_body_from_json(value: Any) -> str:
    if isinstance(value, dict):
        body = value.get("articleBody")
        if isinstance(body, str):
            return clean_text(body)
        for nested in value.values():
            found = _article_body_from_json(nested)
            if found:
                return found
    elif isinstance(value, list):
        for nested in value:
            found = _article_body_from_json(nested)
            if found:
                return found
    return ""


def _publisher_from_json(value: Any) -> str:
    if isinstance(value, dict):
        publisher = value.get("publisher")
        if isinstance(publisher, dict) and isinstance(publisher.get("name"), str):
            return clean_text(publisher["name"])
        for nested in value.values():
            found = _publisher_from_json(nested)
            if found:
                return found
    elif isinstance(value, list):
        for nested in value:
            found = _publisher_from_json(nested)
            if found:
                return found
    return ""


def extract_article_body(html: str, *, url: str = "") -> str:
    parser = _ArticleParser(publisher_hints(url))
    parser.feed(html)
    parser.close()

    for raw in parser.json_ld:
        try:
            body = _article_body_from_json(json.loads(raw))
        except (json.JSONDecodeError, TypeError):
            continue
        if len(body) >= MIN_BODY_LENGTH:
            return body

    candidate = clean_text(" ".join(parser.candidate_chunks))
    if len(candidate) >= MIN_BODY_LENGTH:
        return candidate

    paragraphs = [clean_text(item) for item in parser.paragraphs]
    fallback = " ".join(item for item in paragraphs if len(item) >= 20)
    return clean_text(fallback) if len(clean_text(fallback)) >= MIN_BODY_LENGTH else ""


def extract_page_metadata(html: str, *, url: str = "") -> tuple[str, str]:
    parser = _ArticleParser(publisher_hints(url))
    parser.feed(html)
    parser.close()
    description = max((clean_text(item) for item in parser.meta_descriptions), key=len, default="")
    return parser.canonical_url, description


def extract_page_publisher(html: str, *, url: str = "") -> str:
    parser = _ArticleParser(publisher_hints(url))
    parser.feed(html)
    parser.close()
    for raw in parser.json_ld:
        try:
            publisher = _publisher_from_json(json.loads(raw))
        except (json.JSONDecodeError, TypeError):
            continue
        if publisher:
            return publisher
    return clean_text(parser.site_names[0]) if parser.site_names else ""


def decode_html(raw: bytes, declared_charset: str | None) -> str:
    candidates = [declared_charset or "utf-8", "utf-8", "cp949", "euc-kr"]
    decoded: list[str] = []
    for charset in dict.fromkeys(candidates):
        try:
            decoded.append(raw.decode(charset, errors="replace"))
        except LookupError:
            continue
    if not decoded:
        return raw.decode("utf-8", errors="replace")
    return min(decoded, key=lambda value: (value.count("\ufffd"), -len(re.findall(r"[가-힣]", value))))


def _validate_public_url(url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("지원하지 않는 기사 URL")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("기사 주소를 확인할 수 없음") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise ValueError("내부 네트워크 주소는 수집할 수 없음")


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001, ANN201
        _validate_public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _decode_modern_google_news_token(token: str, timeout_seconds: float) -> str:
    article_url = f"https://news.google.com/rss/articles/{token}?hl=en-US&gl=US&ceid=US:en"
    opener = urllib.request.build_opener(_SafeRedirectHandler())
    page_request = urllib.request.Request(article_url, headers={"User-Agent": USER_AGENT})
    with opener.open(page_request, timeout=timeout_seconds) as response:  # noqa: S310
        page = response.read(1024 * 1024).decode("utf-8", errors="replace")
    params_parser = _GoogleNewsParamsParser()
    params_parser.feed(page)
    params_parser.close()
    serialized = html_lib.unescape(params_parser.data_p)
    if not serialized.startswith("%.@."):
        raise ValueError("Google 뉴스 원문 주소 매개변수 없음")
    try:
        page_data = json.loads(serialized.replace("%.@.", '["garturlreq",', 1))
    except json.JSONDecodeError as exc:
        raise ValueError("Google 뉴스 원문 주소 매개변수 오류") from exc
    if not isinstance(page_data, list) or len(page_data) < 9:
        raise ValueError("Google 뉴스 원문 주소 매개변수 부족")
    request_data = [*page_data[:-6], *page_data[-2:]]
    envelope = [[["Fbv4je", json.dumps(request_data, separators=(",", ":")), None, "generic"]]]
    encoded = urllib.parse.urlencode(
        {"f.req": json.dumps(envelope, separators=(",", ":"))}
    ).encode()
    request = urllib.request.Request(
        GOOGLE_NEWS_BATCH_URL,
        data=encoded,
        headers={
            "User-Agent": USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
            "Referer": "https://news.google.com/",
        },
        method="POST",
    )
    with opener.open(request, timeout=timeout_seconds) as response:  # noqa: S310
        raw = response.read(512 * 1024).decode("utf-8", errors="replace")
    decoded_url = parse_google_news_batch_response(raw)
    _validate_public_url(decoded_url)
    return decoded_url


def parse_google_news_batch_response(raw: str) -> str:
    marker = '[\\"garturlres\\",\\"'
    if marker not in raw:
        raise ValueError("Google 뉴스 원문 주소 해석 실패")
    escaped_url = raw.split(marker, 1)[1].split('\\",', 1)[0]
    decoded_url = json.loads(f'"{escaped_url}"')
    decoded_url = re.sub(
        r"\\u([0-9a-fA-F]{4})",
        lambda match: chr(int(match.group(1), 16)),
        decoded_url,
    )
    return decoded_url


def decode_google_news_url(url: str, timeout_seconds: float = 8) -> str:
    parsed = urllib.parse.urlsplit(url)
    path = parsed.path.rstrip("/").split("/")
    if parsed.hostname != "news.google.com" or len(path) < 2 or path[-2] != "articles":
        return url
    token = path[-1]
    try:
        decoded = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
    except (ValueError, TypeError) as exc:
        raise ValueError("Google 뉴스 주소 형식 오류") from exc
    prefix = b"\x08\x13\x22"
    suffix = b"\xd2\x01\x00"
    if decoded.startswith(prefix):
        decoded = decoded[len(prefix):]
    if decoded.endswith(suffix):
        decoded = decoded[:-len(suffix)]
    if not decoded:
        raise ValueError("Google 뉴스 주소 내용 없음")
    if decoded[0] >= 0x80:
        if len(decoded) < 2:
            raise ValueError("Google 뉴스 주소 길이 오류")
        length = (decoded[0] & 0x7F) | (decoded[1] << 7)
        candidate = decoded[2:2 + length]
    else:
        length = decoded[0]
        candidate = decoded[1:1 + length]
    text = candidate.decode("utf-8", errors="replace")
    if text.startswith("AU_yqL"):
        return _decode_modern_google_news_token(token, timeout_seconds)
    if text.startswith(("http://", "https://")):
        _validate_public_url(text)
        return text
    raise ValueError("Google 뉴스 원문 주소를 찾지 못함")


def _fetch_page(url: str, timeout_seconds: float) -> tuple[str, str, str]:
    _validate_public_url(url)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "ko-KR,ko;q=0.9",
        },
    )
    opener = urllib.request.build_opener(_SafeRedirectHandler())
    with opener.open(request, timeout=timeout_seconds) as response:  # noqa: S310
        content_type = response.headers.get_content_type()
        if content_type not in {"text/html", "application/xhtml+xml"}:
            raise ValueError(f"HTML 문서가 아님 ({content_type})")
        raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError("기사 문서가 허용 크기를 초과함")
        html = decode_html(raw, response.headers.get_content_charset())
        final_url = response.geturl()
    _, description = extract_page_metadata(html, url=final_url)
    return html, final_url, description


def _failure_reason(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code in {401, 403, 406, 429, 451}:
            return "access_blocked"
        return "network_error"
    message = str(exc).lower()
    if "paywall" in message or "유료" in message:
        return "paywall"
    if isinstance(exc, ValueError) and "google 뉴스" in message:
        return "redirect_failed"
    return "network_error"


def fetch_article_body_with_retries(
    url: str,
    timeout_seconds: float = 8,
    body_validator: Callable[[str, str], bool] | None = None,
) -> BodyFetchResult:
    if not url:
        return BodyFetchResult("", "failed", "기사 URL 없음", attempts=())
    attempts: list[dict[str, str]] = []
    try:
        resolved_source = decode_google_news_url(url, timeout_seconds)
    except (ValueError, urllib.error.URLError, TimeoutError, OSError) as exc:
        return BodyFetchResult(
            "", "failed", _failure_reason(exc), attempts=({"stage": "resolve", "error": str(exc)},)
        )
    candidates = [("original", resolved_source), *alternate_urls(resolved_source)]
    summary = ""
    final_url = resolved_source
    for stage, candidate_url in candidates:
        try:
            html, final_url, description = _fetch_page(candidate_url, timeout_seconds)
            summary = max(summary, description, key=len)
            canonical, _ = extract_page_metadata(html, url=final_url)
            canonical = urllib.parse.urljoin(final_url, canonical) if canonical else ""
            page_publisher = extract_page_publisher(html, url=final_url)
            body = extract_article_body(html, url=final_url)
            if body and (body_validator is None or body_validator(body, final_url)):
                attempts.append({"stage": stage, "url": candidate_url, "status": "success"})
                return BodyFetchResult(
                    body, "success_full", "", final_url, tuple(attempts), canonical, page_publisher
                )
            attempts.append({
                "stage": stage, "url": candidate_url,
                "status": "quality_failed" if body else "selector_failed",
            })
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, ValueError, LookupError) as exc:
            attempts.append(
                {"stage": stage, "url": candidate_url, "status": _failure_reason(exc), "error": str(exc)}
            )
    if len(summary) >= 120:
        return BodyFetchResult(summary, "success_summary", "", final_url, tuple(attempts))
    reason = attempts[-1]["status"] if attempts else "network_error"
    return BodyFetchResult("", "failed", reason, final_url, tuple(attempts))


def fetch_article_body(url: str, timeout_seconds: float = 8) -> BodyFetchResult:
    if not url:
        return BodyFetchResult("", "missing", "기사 URL 없음")
    try:
        url = decode_google_news_url(url, timeout_seconds)
        html, resolved_url, _ = _fetch_page(url, timeout_seconds)
        body = extract_article_body(html, url=resolved_url)
        if not body:
            return BodyFetchResult("", "missing", "기사 본문 영역을 찾지 못함")
        return BodyFetchResult(body, "full_text", resolved_url=resolved_url)
    except urllib.error.HTTPError as exc:
        return BodyFetchResult("", "missing", f"언론사 응답 HTTP {exc.code}")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, LookupError) as exc:
        return BodyFetchResult("", "missing", str(exc) or "기사 전문 수집 실패")
