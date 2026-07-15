#!/usr/bin/env python3
from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = BASE_DIR / "config" / "automated_collection.json"
ENDPOINT = "http://127.0.0.1:8787/api/collections"


def main() -> int:
    if not CONFIG_PATH.is_file():
        print(f"자동수집 설정이 없습니다: {CONFIG_PATH}")
        return 2
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    payload["reportDate"] = datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
    request = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"자동수집 요청 실패: {exc}")
        return 1
    if not body.get("ok"):
        print(f"자동수집 API 오류: {body.get('error')}")
        return 1
    data = body.get("data") or {}
    print(
        f"자동수집 {data.get('status')}: 보고일 {payload['reportDate']}, "
        f"신규 {data.get('newCount', 0)}건, 고유 {data.get('uniqueCount', 0)}건"
    )
    return 0 if data.get("status") in {"success", "partial"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
