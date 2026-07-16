#!/usr/bin/env python3
from __future__ import annotations

import fcntl
import os
from pathlib import Path

import uvicorn

from backend.app.core.env import load_env

BASE_DIR = Path(__file__).resolve().parents[1]
LOCK_PATH = BASE_DIR / "data" / "server.lock"


def main() -> int:
    load_env(BASE_DIR / ".env")
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("a+", encoding="utf-8") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("KESCO 브리핑 서버가 이미 실행 중입니다.")
            return 73
        lock_file.seek(0)
        lock_file.truncate()
        lock_file.write(str(os.getpid()))
        lock_file.flush()
        uvicorn.run("backend.app.main:app", host="127.0.0.1", port=8787)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
