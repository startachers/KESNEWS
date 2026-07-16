#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
RUN_SERVER = BASE_DIR / "scripts" / "run_server.py"
LOG_PATH = BASE_DIR / "logs" / "app.log"
LAUNCHD_LABEL = "kr.or.kesco.media-briefing.server"


def log(message: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as stream:
        stream.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {message}\n")


def launchd_server_pid() -> int | None:
    target = f"gui/{os.getuid()}/{LAUNCHD_LABEL}"
    result = subprocess.run(  # noqa: S603,S607 - macOS의 고정 launchctl 명령만 실행한다.
        ["launchctl", "print", target],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    match = re.search(r"^\s*pid = (\d+)\s*$", result.stdout, re.MULTILINE)
    return int(match.group(1)) if match else None


def process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def restart(parent_pid: int) -> int:
    # API 응답이 브라우저까지 전달될 시간을 확보한다.
    time.sleep(0.75)
    target = f"gui/{os.getuid()}/{LAUNCHD_LABEL}"
    if launchd_server_pid() == parent_pid:
        log("브라우저 요청으로 launchd 서버를 재시작합니다.")
        result = subprocess.run(  # noqa: S603,S607 - 고정 launchctl job만 재시작한다.
            ["launchctl", "kickstart", "-k", target], check=False
        )
        return result.returncode

    log("브라우저 요청으로 수동 실행 서버를 재시작합니다.")
    try:
        os.kill(parent_pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    for _ in range(200):
        if not process_exists(parent_pid):
            os.execv(sys.executable, [sys.executable, str(RUN_SERVER)])
        time.sleep(0.1)
    log("기존 서버가 제한 시간 내 종료되지 않아 재시작을 중단했습니다.")
    return 1


def main() -> int:
    if len(sys.argv) != 2 or not sys.argv[1].isdigit():
        return 2
    return restart(int(sys.argv[1]))


if __name__ == "__main__":
    raise SystemExit(main())
