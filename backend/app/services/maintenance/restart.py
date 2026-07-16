from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[4]
RESTART_HELPER = BASE_DIR / "scripts" / "restart_server.py"


def schedule_server_restart(parent_pid: int) -> None:
    """응답이 전달된 뒤 독립 프로세스가 현재 서버를 안전하게 교체하도록 예약한다."""
    subprocess.Popen(  # noqa: S603 - 고정된 로컬 스크립트와 현재 Python만 실행한다.
        [sys.executable, str(RESTART_HELPER), str(parent_pid)],
        cwd=BASE_DIR,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )
