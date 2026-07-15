#!/bin/bash
set -euo pipefail
cd "$(cd "$(dirname "$0")" && pwd)"

PYTHON_BIN=""
for candidate in python3.13 python3.12 python3.11 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    version="$("$candidate" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
    major="${version%%.*}"
    minor="${version##*.}"
    if [ "$major" -eq 3 ] && [ "$minor" -ge 11 ]; then
      PYTHON_BIN="$candidate"
      break
    fi
  fi
done

if [ -z "$PYTHON_BIN" ]; then
  echo "Python 3.11 이상을 찾을 수 없습니다. 예: brew install python@3.12" >&2
  exit 1
fi

echo "사용할 Python: $("$PYTHON_BIN" --version)"

if [ ! -d ".venv" ]; then
  echo ".venv 생성 중..."
  "$PYTHON_BIN" -m venv .venv
fi

echo "의존성 설치 중..."
".venv/bin/pip" install --upgrade pip >/dev/null
".venv/bin/pip" install -e . >/dev/null

mkdir -p logs data backups reports

chmod +x setup_kesco_briefing.command start_kesco_briefing.command

echo "설정 완료. start_kesco_briefing.command로 앱을 실행하세요."
