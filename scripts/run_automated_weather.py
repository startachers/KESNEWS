#!/usr/bin/env python3
from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from backend.app.core.env import load_env

BASE_DIR = Path(__file__).resolve().parents[1]
ENDPOINT = "http://127.0.0.1:8787/api/weather/refresh"


def main() -> int:
    load_env(BASE_DIR / ".env")
    report_date = datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
    request = urllib.request.Request(
        ENDPOINT,
        data=json.dumps({"reportDate": report_date}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"기상 자동수집 요청 실패: {exc}")
        return 1
    if not body.get("ok"):
        print(f"기상 자동수집 API 오류: {body.get('error')}")
        return 1
    run = (body.get("data") or {}).get("latestRun") or {}
    print(
        f"기상 자동수집 {run.get('status')}: 보고일 {report_date}, "
        f"경고 {run.get('warningCount', 0)}건, 오류 {run.get('errorCount', 0)}건"
    )
    return 0 if run.get("status") in {"success", "partial"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
