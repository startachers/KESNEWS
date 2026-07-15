from __future__ import annotations

import sqlite3

import pytest

from backend.app.repositories.database import backup_database, check_database_integrity
from backend.app.services.maintenance.backup import RestoreError, list_valid_backups, restore_database


def _create_database(path, value: str) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE sample (value TEXT NOT NULL)")
        connection.execute("INSERT INTO sample VALUES (?)", (value,))
        connection.commit()
    finally:
        connection.close()


def test_online_backup_is_integral_and_prunes_old_files(tmp_path):
    source = tmp_path / "source.db"
    backup_dir = tmp_path / "backups"
    _create_database(source, "보존할 값")

    paths = [
        backup_database(source, backup_dir=backup_dir, keep_count=2) for _ in range(3)
    ]

    assert all(path is not None for path in paths)
    assert len(list(backup_dir.glob("*.db"))) == 2
    assert list(backup_dir.glob("*.db-wal")) == []
    assert list(backup_dir.glob("*.db-shm")) == []
    latest = list_valid_backups(backup_dir)[0]
    assert latest["valid"] is True
    assert check_database_integrity(paths[-1]) == (True, "ok")
    connection = sqlite3.connect(paths[-1])
    try:
        assert connection.execute("SELECT value FROM sample").fetchone()[0] == "보존할 값"
    finally:
        connection.close()


def test_restore_replaces_target_and_rejects_corrupt_source(tmp_path):
    source = tmp_path / "backup.db"
    target = tmp_path / "target.db"
    _create_database(source, "복구 값")
    _create_database(target, "기존 값")

    restore_database(source, target)

    connection = sqlite3.connect(target)
    try:
        assert connection.execute("SELECT value FROM sample").fetchone()[0] == "복구 값"
    finally:
        connection.close()

    corrupt = tmp_path / "corrupt.db"
    corrupt.write_text("not sqlite", encoding="utf-8")
    with pytest.raises(RestoreError, match="무결성"):
        restore_database(corrupt, target)
