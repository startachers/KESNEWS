from __future__ import annotations

import json
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[4]
CONFIG_PATH = BASE_DIR / "config" / "weather_regions.json"


def load_regions() -> dict[str, Any]:
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if not payload.get("version") or not isinstance(payload.get("regions"), list):
        raise ValueError("기상 권역 설정의 version 또는 regions가 올바르지 않습니다.")
    ids = [str(item.get("id") or "") for item in payload["regions"]]
    if not all(ids) or len(ids) != len(set(ids)):
        raise ValueError("기상 권역 ID가 비어 있거나 중복됐습니다.")
    return payload
