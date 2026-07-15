#!/bin/bash
set -euo pipefail
cd "$(cd "$(dirname "$0")" && pwd)"

if [ ! -x ".venv/bin/python" ]; then
  echo "가상환경이 없습니다. 먼저 setup_kesco_briefing.command를 실행하세요." >&2
  exit 1
fi

exec ".venv/bin/python" scripts/install_launchd.py "${1:-install}"
