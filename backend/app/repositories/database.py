from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from backend.app.db.migrator import apply_migrations, pending_migrations

BASE_DIR = Path(__file__).resolve().parents[3]
DATA_DIR = BASE_DIR / "data"
# 테스트는 KESCO_DB_PATH/KESCO_BACKUPS_DIR로 임시 경로를 지정해 실제 운영 data/backups를 건드리지 않는다.
DB_PATH = Path(os.environ["KESCO_DB_PATH"]) if os.environ.get("KESCO_DB_PATH") else DATA_DIR / "kesco_media_briefing.db"
BACKUPS_DIR = (
    Path(os.environ["KESCO_BACKUPS_DIR"])
    if os.environ.get("KESCO_BACKUPS_DIR")
    else BASE_DIR / "backups" / "db"
)
BACKUP_KEEP_COUNT = int(os.environ.get("KESCO_BACKUP_KEEP_COUNT", "30"))


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


def check_database_integrity(db_path: Path = DB_PATH) -> tuple[bool, str]:
    if not db_path.exists():
        return False, "database file not found"
    try:
        connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            row = connection.execute("PRAGMA integrity_check").fetchone()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        return False, str(exc)
    result = str(row[0]) if row else "integrity_check returned no result"
    return result == "ok", result


def _prune_backups(backup_dir: Path, keep_count: int) -> None:
    if keep_count < 1:
        return
    candidates = sorted(backup_dir.glob("*.db"), key=lambda path: path.stat().st_mtime, reverse=True)
    for expired in candidates[keep_count:]:
        expired.unlink(missing_ok=True)


def backup_database(
    db_path: Path = DB_PATH,
    *,
    backup_dir: Path = BACKUPS_DIR,
    keep_count: int = BACKUP_KEEP_COUNT,
) -> Path | None:
    """SQLite online backup으로 WAL의 커밋 내용까지 일관된 단일 DB 파일에 보존한다."""
    if not db_path.exists():
        return None
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    target = backup_dir / f"{stamp}.db"
    sequence = 1
    while target.exists():
        target = backup_dir / f"{stamp}_{sequence}.db"
        sequence += 1
    source = sqlite3.connect(db_path)
    destination = sqlite3.connect(target)
    try:
        source.backup(destination)
        destination.execute("PRAGMA journal_mode = DELETE")
    finally:
        destination.close()
        source.close()
    valid, detail = check_database_integrity(target)
    if not valid:
        target.unlink(missing_ok=True)
        raise sqlite3.DatabaseError(f"백업 무결성 검사 실패: {detail}")
    _prune_backups(backup_dir, keep_count)
    return target


def init_db(db_path: Path = DB_PATH) -> list[str]:
    """앱 시작 시 호출한다. 대기 중인 migration이 있으면 먼저 DB 파일을 백업한 뒤 적용한다."""
    if db_path.exists():
        valid, detail = check_database_integrity(db_path)
        if not valid:
            raise sqlite3.DatabaseError(f"DB 무결성 검사 실패: {detail}")
    connection = get_connection(db_path)
    try:
        if pending_migrations(connection):
            backup_database(db_path)
        applied = apply_migrations(connection)
        _backfill_phase5_assessments(connection)
        _backfill_issue_review_assessments(connection)
        return applied
    finally:
        connection.close()


def _backfill_phase5_assessments(connection: sqlite3.Connection) -> None:
    """누락됐거나 구버전인 자동 판정을 재계산한다. upsert는 final_* 컬럼을 갱신하지 않는다."""
    from backend.app.repositories import article_repository as article_repo
    from backend.app.services.classification.service import CLASSIFIER_VERSION, classify_article

    rows = connection.execute(
        """
        SELECT
            a.id,
            a.title,
            a.description,
            a.body_text,
            EXISTS (
                SELECT 1
                FROM article_observations ao
                WHERE ao.article_id = a.id
                  AND ao.provider IN (
                      '국무조정실 보도자료',
                      '기후에너지환경부 보도자료',
                      '정책브리핑 API'
                  )
            ) AS official_government
        FROM articles a
        JOIN article_assessments aa ON aa.article_id = a.id
        WHERE aa.auto_priority IS NULL OR aa.classifier_version != ?
        """,
        (CLASSIFIER_VERSION,),
    ).fetchall()
    with connection:
        for row in rows:
            classified = classify_article(
                {
                    "title": row["title"],
                    "description": row["description"] or "",
                    "bodyText": row["body_text"] or "",
                    "_official_government": bool(row["official_government"]),
                }
            )
            article_repo.upsert_assessment(
                connection,
                article_id=row["id"],
                assessment=classified["assessment"],
                classifier_version=CLASSIFIER_VERSION,
            )


def _backfill_issue_review_assessments(connection: sqlite3.Connection) -> None:
    """migration 직후 기존 보고일 군집에 검토순위가 없을 때 한 번 계산한다."""
    from backend.app.repositories import issue_repository as issue_repo

    rows = connection.execute(
        """
        SELECT b.report_date
        FROM briefings b
        WHERE NOT EXISTS (
            SELECT 1 FROM issue_review_assessments ira WHERE ira.briefing_id = b.id
        )
          AND EXISTS (
            SELECT 1 FROM cluster_runs cr
            WHERE cr.report_date = b.report_date AND cr.status = 'applied'
        )
        """
    ).fetchall()
    with connection:
        for row in rows:
            issue_repo.recalculate_review_assessments(connection, row["report_date"])
