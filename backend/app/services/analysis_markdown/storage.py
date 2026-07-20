from __future__ import annotations

import os
import tempfile
from pathlib import Path

from backend.app.services.analysis_markdown.config import PROJECT_ROOT


def target_path(report_date: str, *, validation: bool = False) -> Path:
    if not __import__("re").fullmatch(r"\d{4}-\d{2}-\d{2}", report_date):
        raise ValueError("보고일 형식이 올바르지 않습니다.")
    # 테스트와 별도 운영 데이터 디렉터리가 프로젝트 reports/를 오염시키지 않도록
    # 기존 보고서 저장소와 같은 KESCO_REPORTS_DIR 계약을 따른다.
    reports_root = Path(os.environ.get("KESCO_REPORTS_DIR") or PROJECT_ROOT / "reports")
    base = reports_root / "ai_inputs"
    if validation:
        base /= "_validation"
    return base / report_date / f"KESCO_AI분석자료_{report_date}.md"


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
