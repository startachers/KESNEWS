from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

_GDELT_DATE = re.compile(r"^\d{8}T\d{6}Z$")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_date(value: str | None) -> str:
    """RFC 822(RSS pubDate)와 ISO 8601을 모두 허용한다. frontend parseDate()의 new Date(value) 관용도 포팅."""
    if not value:
        return _now_iso()
    text = str(value).strip()
    try:
        dt = parsedate_to_datetime(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError):
        pass
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except ValueError:
        return _now_iso()


def parse_gdelt_date(value: str | None) -> str:
    if value and _GDELT_DATE.match(value):
        iso = f"{value[0:4]}-{value[4:6]}-{value[6:8]}T{value[9:11]}:{value[11:13]}:{value[13:15]}Z"
        return parse_date(iso)
    return parse_date(value)


def since_bound_iso(reference_iso: str | None, hours: int) -> str:
    """reference_iso로부터 hours시간 이전 시각을 ISO로 반환한다. 기사 매칭 후보 범위를 좁히는 데 쓴다."""
    reference = reference_iso or _now_iso()
    try:
        dt = datetime.fromisoformat(str(reference).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except ValueError:
        dt = datetime.now(timezone.utc)
    bound = dt.astimezone(timezone.utc) - timedelta(hours=hours)
    return bound.isoformat().replace("+00:00", "Z")


def date_value(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp() * 1000
    except ValueError:
        return 0.0
