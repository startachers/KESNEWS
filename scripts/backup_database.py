#!/usr/bin/env python3
from __future__ import annotations

from backend.app.repositories.database import backup_database


def main() -> int:
    path = backup_database()
    if path is None:
        print("백업할 운영 DB가 없습니다.")
        return 1
    print(f"DB 백업 완료: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
