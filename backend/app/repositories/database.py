from __future__ import annotations

import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from backend.app.db.migrator import apply_migrations, pending_migrations

BASE_DIR = Path(__file__).resolve().parents[3]
DATA_DIR = BASE_DIR / "data"
# 테스트는 KESCO_DB_PATH/KESCO_BACKUPS_DIR로 임시 경로를 지정해 실제 운영 data/backups를 건드리지 않는다.
DB_PATH = Path(os.environ["KESCO_DB_PATH"]) if os.environ.get("KESCO_DB_PATH") else DATA_DIR / "kesco_media_briefing.db"
BACKUPS_DIR = Path(os.environ["KESCO_BACKUPS_DIR"]) if os.environ.get("KESCO_BACKUPS_DIR") else BASE_DIR / "backups"


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
        applied = apply_migrations(connection)
        _backfill_phase5_assessments(connection)
        return applied
    finally:
        connection.close()


def _backfill_phase5_assessments(connection: sqlite3.Connection) -> None:
    """Phase 4 판정행을 새 축으로 재계산한다. upsert는 final_* 컬럼을 갱신하지 않는다."""
    from backend.app.repositories import article_repository as article_repo
    from backend.app.services.classification.service import CLASSIFIER_VERSION, classify_article

    rows = connection.execute(
        """
        SELECT a.id, a.title, a.description, aa.auto_category
        FROM articles a
        JOIN article_assessments aa ON aa.article_id = a.id
        WHERE aa.auto_priority IS NULL
        """
    ).fetchall()
    with connection:
        for row in rows:
            classified = classify_article(
                {
                    "title": row["title"],
                    "description": row["description"] or "",
                    "category": row["auto_category"],
                }
            )
            article_repo.upsert_assessment(
                connection,
                article_id=row["id"],
                assessment=classified["assessment"],
                classifier_version=CLASSIFIER_VERSION,
            )
