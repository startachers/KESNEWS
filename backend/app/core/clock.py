from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

SEOUL_TZ = ZoneInfo("Asia/Seoul")


def today_seoul() -> str:
    return datetime.now(SEOUL_TZ).date().isoformat()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
