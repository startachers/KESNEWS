from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


POLICY_PATH = Path(__file__).resolve().parents[4] / "config" / "kesco_jurisdiction.json"


@lru_cache(maxsize=1)
def load_jurisdiction_policy() -> dict[str, Any]:
    """Load the policy used by both prompts and deterministic server validation."""
    payload = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    required = {
        "version",
        "direct",
        "collaborative",
        "monitoring",
        "out_of_scope",
        "blocked_if_absent",
        "authority_only_phrases",
    }
    missing = sorted(required - payload.keys())
    if missing:
        raise ValueError(f"KESCO 소관 정책 필드가 없습니다: {', '.join(missing)}")
    return payload


def jurisdiction_policy_text() -> str:
    return json.dumps(load_jurisdiction_policy(), ensure_ascii=False, indent=2)
