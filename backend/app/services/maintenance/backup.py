from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from backend.app.repositories.database import BACKUPS_DIR, DB_PATH, backup_database, check_database_integrity


class RestoreError(Exception):
    pass


def list_valid_backups(backup_dir: Path = BACKUPS_DIR) -> list[dict[str, str | int | bool]]:
    if not backup_dir.exists():
        return []
    result = []
    for path in sorted(backup_dir.glob("*.db"), key=lambda item: item.stat().st_mtime, reverse=True):
        valid, detail = check_database_integrity(path)
        result.append(
            {
                "path": str(path),
                "name": path.name,
                "sizeBytes": path.stat().st_size,
                "valid": valid,
                "integrity": detail,
            }
        )
    return result


def restore_database(source: Path, target: Path = DB_PATH) -> Path | None:
    """검증된 백업을 임시 파일에 복제한 뒤 원자적으로 운영 DB와 교체한다.

    호출자는 서버가 중지됐음을 보장해야 한다. 교체 직전 현재 DB도 온라인 백업한다.
    """
    source = source.resolve()
    target = target.resolve()
    if source == target:
        raise RestoreError("백업 파일과 복구 대상이 같습니다.")
    valid, detail = check_database_integrity(source)
    if not valid:
        raise RestoreError(f"선택한 백업의 무결성 검사 실패: {detail}")

    target.parent.mkdir(parents=True, exist_ok=True)
    safety_backup = backup_database(target) if target.exists() else None
    temporary = target.with_suffix(".restore.tmp")
    temporary.unlink(missing_ok=True)
    source_connection = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    target_connection = sqlite3.connect(temporary)
    try:
        source_connection.backup(target_connection)
        target_connection.execute("PRAGMA journal_mode = DELETE")
    finally:
        target_connection.close()
        source_connection.close()

    valid, detail = check_database_integrity(temporary)
    if not valid:
        temporary.unlink(missing_ok=True)
        raise RestoreError(f"복구 임시 DB 무결성 검사 실패: {detail}")
    os.replace(temporary, target)
    target.with_name(f"{target.name}-wal").unlink(missing_ok=True)
    target.with_name(f"{target.name}-shm").unlink(missing_ok=True)
    return safety_backup
