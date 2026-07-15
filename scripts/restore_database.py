#!/usr/bin/env python3
from __future__ import annotations

import argparse
import socket
from pathlib import Path

from backend.app.repositories.database import BACKUPS_DIR
from backend.app.services.maintenance.backup import RestoreError, list_valid_backups, restore_database


def _server_is_running() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 8787), timeout=0.5):
            return True
    except OSError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="KESCO 브리핑 SQLite 백업 복구")
    parser.add_argument("backup", nargs="?", help="복구할 .db 파일. 생략하면 최근 정상 백업")
    parser.add_argument("--yes", action="store_true", help="복구 확인을 생략")
    args = parser.parse_args()

    if _server_is_running():
        print("8787 포트의 앱을 먼저 종료한 뒤 복구하세요.")
        return 2

    if args.backup:
        source = Path(args.backup)
    else:
        valid = [item for item in list_valid_backups() if item["valid"]]
        if not valid:
            print(f"정상 백업이 없습니다: {BACKUPS_DIR}")
            return 1
        source = Path(str(valid[0]["path"]))

    if not args.yes:
        answer = input(f"{source} 백업으로 운영 DB를 복구합니까? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            print("복구를 취소했습니다.")
            return 0
    try:
        safety = restore_database(source)
    except RestoreError as exc:
        print(f"복구 실패: {exc}")
        return 1
    print(f"복구 완료: {source}")
    if safety:
        print(f"복구 직전 DB 안전 백업: {safety}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
