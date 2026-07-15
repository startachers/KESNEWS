#!/bin/bash
set -euo pipefail
cd "$(cd "$(dirname "$0")" && pwd)"

HOST="127.0.0.1"
PORT="8787"
URL="http://${HOST}:${PORT}/"
HEALTH_URL="http://${HOST}:${PORT}/api/health"
LOG_DIR="logs"
LOG_FILE="${LOG_DIR}/app.log"
mkdir -p "$LOG_DIR"

log() {
  echo "$(date '+%Y-%m-%d %H:%M:%S') $1" | tee -a "$LOG_FILE"
}

is_healthy() {
  curl -sf --max-time 2 "$HEALTH_URL" 2>/dev/null | grep -q '"service":"kesco-media-briefing"'
}

if is_healthy; then
  log "이미 실행 중인 서버 감지 (${HEALTH_URL}). 새 서버를 띄우지 않고 브라우저만 엽니다."
  open "$URL"
  exit 0
fi

if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  log "포트 ${PORT}을 다른 프로세스가 사용 중입니다. lsof -nP -iTCP:${PORT} -sTCP:LISTEN 으로 확인하세요."
  exit 1
fi

if [ ! -x ".venv/bin/uvicorn" ]; then
  echo "가상환경이 없습니다. 먼저 setup_kesco_briefing.command를 실행하세요." >&2
  exit 1
fi

if curl -sf --max-time 1 "http://127.0.0.1:11434/api/tags" >/dev/null 2>&1; then
  log "Ollama 감지됨 (127.0.0.1:11434)."
else
  log "Ollama 미감지. models: []로 서비스됩니다."
fi

log "FastAPI 서버 시작 중 (${HOST}:${PORT})..."
nohup ".venv/bin/python" scripts/run_server.py >>"$LOG_FILE" 2>&1 &
SERVER_PID=$!
log "서버 PID: ${SERVER_PID}"

READY=0
for _ in $(seq 1 30); do
  if is_healthy; then
    READY=1
    break
  fi
  sleep 0.5
done

if [ "$READY" -eq 1 ]; then
  log "health 확인 완료. 브라우저를 엽니다."
  open "$URL"
else
  log "서버가 제한 시간 내에 응답하지 않았습니다. 로그(${LOG_FILE})를 확인하세요."
  exit 1
fi
