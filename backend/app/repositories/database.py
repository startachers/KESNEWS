from __future__ import annotations

import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from backend.app.db.migrator import apply_migrations, pending_migrations

BASE_DIR = Path(__file__).resolve().parents[3]
DATA_DIR = BASE_DIR / "data"
BACKUPS_DIR = BASE_DIR / "backups"
# 테스트는 KESCO_DB_PATH로 임시 파일을 지정해 실제 운영 DB(data/)를 건드리지 않는다.
DB_PATH = Path(os.environ["KESCO_DB_PATH"]) if os.environ.get("KESCO_DB_PATH") else DATA_DIR / "kesco_media_briefing.db"


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


def backup_database(db_path: Path = DB_PATH) -> Path | None:
    if not db_path.exists():
        return None
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = BACKUPS_DIR / f"{db_path.stem}_{stamp}.db"
    shutil.copy2(db_path, target)
    return target


def init_db(db_path: Path = DB_PATH) -> list[str]:
    """앱 시작 시 호출한다. 대기 중인 migration이 있으면 먼저 DB 파일을 백업한 뒤 적용한다."""
    connection = get_connection(db_path)
    try:
        if pending_migrations(connection):
            backup_database(db_path)
        return apply_migrations(connection)
    finally:
        connection.close()
