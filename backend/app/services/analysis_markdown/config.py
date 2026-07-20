from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.app.services.extraction.cleaner import CLEANING_RULE_VERSION

PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_PATH = PROJECT_ROOT / "config" / "analysis_markdown.yaml"


def load_config(path: Path = DEFAULT_PATH) -> dict[str, Any]:
    # JSON은 YAML 1.2의 부분집합이다. 별도 운영 의존성 없이 설정을 엄격하게 읽는다.
    with path.open(encoding="utf-8") as stream:
        config = json.load(stream)
    required = {
        "version", "cleaning_rule_version", "minimum_full_text_characters",
        "minimum_rss_summary_characters", "article_character_limits", "document_budget",
        "publisher_quality",
    }
    missing = sorted(required - set(config))
    if missing:
        raise ValueError(f"analysis markdown 설정 누락: {', '.join(missing)}")
    if config["cleaning_rule_version"] != CLEANING_RULE_VERSION:
        raise ValueError("정제 규칙 구현 버전과 analysis markdown 설정 버전이 다릅니다.")
    return config
