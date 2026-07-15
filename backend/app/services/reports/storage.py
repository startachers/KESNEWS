from __future__ import annotations

import os
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[4]
REPORTS_DIR = (
    Path(os.environ["KESCO_REPORTS_DIR"])
    if os.environ.get("KESCO_REPORTS_DIR")
    else BASE_DIR / "reports"
)
BRIEFING_BACKUPS_DIR = (
    Path(os.environ["KESCO_BRIEFING_BACKUPS_DIR"])
    if os.environ.get("KESCO_BRIEFING_BACKUPS_DIR")
    else BASE_DIR / "backups" / "briefing"
)


def report_path(report_date: str, version: int) -> Path:
    year, month, _ = report_date.split("-", 2)
    return REPORTS_DIR / year / month / f"KESCO_{report_date}_v{version}.html"


def write_report(report_date: str, version: int, html: str) -> Path:
    path = report_path(report_date, version)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(html, encoding="utf-8")
    temporary.replace(path)
    return path


def write_snapshot_backup(report_date: str, version: int, snapshot: dict) -> Path:
    path = BRIEFING_BACKUPS_DIR / f"{report_date}_v{version}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    temporary.replace(path)
    return path
