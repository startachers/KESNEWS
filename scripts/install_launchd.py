#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import plistlib
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
SERVER_LABEL = "kr.or.kesco.media-briefing.server"
COLLECTION_LABEL = "kr.or.kesco.media-briefing.collection"
WEATHER_LABEL = "kr.or.kesco.media-briefing.weather"


def _paths(label: str) -> Path:
    return AGENTS_DIR / f"{label}.plist"


def _write_plist(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("wb") as stream:
        plistlib.dump(payload, stream, sort_keys=True)
    temporary.replace(path)


def _bootout(path: Path) -> None:
    subprocess.run(
        ["launchctl", "bootout", f"gui/{os.getuid()}", str(path)],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def install() -> int:
    python = BASE_DIR / ".venv" / "bin" / "python"
    if not python.is_file():
        print("가상환경이 없습니다. setup_kesco_briefing.command를 먼저 실행하세요.")
        return 1
    logs = BASE_DIR / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    common = {
        "WorkingDirectory": str(BASE_DIR),
        "ProcessType": "Background",
    }
    server_path = _paths(SERVER_LABEL)
    collection_path = _paths(COLLECTION_LABEL)
    weather_path = _paths(WEATHER_LABEL)
    _write_plist(
        server_path,
        {
            **common,
            "Label": SERVER_LABEL,
            "ProgramArguments": [str(python), str(BASE_DIR / "scripts" / "run_server.py")],
            "RunAtLoad": True,
            "KeepAlive": {"SuccessfulExit": False},
            "ThrottleInterval": 30,
            "StandardOutPath": str(logs / "launchd-server.log"),
            "StandardErrorPath": str(logs / "launchd-server.log"),
        },
    )
    _write_plist(
        collection_path,
        {
            **common,
            "Label": COLLECTION_LABEL,
            "ProgramArguments": [
                str(python),
                str(BASE_DIR / "scripts" / "run_automated_collection.py"),
            ],
            "StartInterval": 7200,
            "ThrottleInterval": 300,
            "StandardOutPath": str(logs / "collection.log"),
            "StandardErrorPath": str(logs / "collection.log"),
        },
    )
    _write_plist(
        weather_path,
        {
            **common,
            "Label": WEATHER_LABEL,
            "ProgramArguments": [
                str(python),
                str(BASE_DIR / "scripts" / "run_automated_weather.py"),
            ],
            "StartInterval": 7200,
            "ThrottleInterval": 300,
            "StandardOutPath": str(logs / "weather.log"),
            "StandardErrorPath": str(logs / "weather.log"),
        },
    )
    for path in (server_path, collection_path, weather_path):
        _bootout(path)
        subprocess.run(
            ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(path)], check=True
        )
    print("launchd 설치 완료: 로그인 시 서버 시작, 2시간마다 기사·기상 자동수집")
    print("자동수집 설정: 웹 화면의 검색 설정(/api/settings)")
    return 0


def uninstall() -> int:
    for label in (WEATHER_LABEL, COLLECTION_LABEL, SERVER_LABEL):
        path = _paths(label)
        _bootout(path)
        path.unlink(missing_ok=True)
    print("KESCO 브리핑 launchd 항목을 제거했습니다. 데이터와 백업은 유지됩니다.")
    return 0


def status() -> int:
    result = 0
    for label in (SERVER_LABEL, COLLECTION_LABEL, WEATHER_LABEL):
        completed = subprocess.run(
            ["launchctl", "print", f"gui/{os.getuid()}/{label}"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        state = "등록됨" if completed.returncode == 0 else "미등록"
        print(f"{label}: {state}")
        result = max(result, completed.returncode)
    return 0 if result == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="KESCO 브리핑 launchd 관리")
    parser.add_argument("action", nargs="?", choices=("install", "uninstall", "status"), default="install")
    args = parser.parse_args()
    return {"install": install, "uninstall": uninstall, "status": status}[args.action]()


if __name__ == "__main__":
    raise SystemExit(main())
