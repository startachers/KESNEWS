# KESCO 언론브리핑 운영·장애복구 절차

## 정상 운영

1. `./start_kesco_briefing.command`로 실행한다.
2. `http://127.0.0.1:8787/api/health`에서 `service=kesco-media-briefing`,
   `dbConnected=true`, `dbIntegrity=true`를 확인한다.
3. `http://127.0.0.1:8787/api/operations/status`에서 최근 수집, 마지막 정상 수집,
   최근 DB 백업을 확인한다.
4. 최종 확정 뒤 `reports/YYYY/MM/`의 HTML과 `backups/briefing/YYYY-MM-DD_vN.json`이
   같은 version인지 확인한다.

로그는 `logs/app.log`, `logs/collection.log`, `logs/ai.log`에 남고 각각 5 MiB에서
회전하며 과거 5개를 보존한다. 기사 원문이나 API key는 기록하지 않는다.

## launchd

`./install_launchd.command install`은 두 LaunchAgent를 등록한다.

- `kr.or.kesco.media-briefing.server`: 로그인 시 시작, 비정상 종료 시 재시작
- `kr.or.kesco.media-briefing.collection`: 2시간 간격 자동수집

상태는 `./install_launchd.command status`, 제거는 `./install_launchd.command uninstall`로
확인한다. 자동수집 설정은 Git 비추적 파일 `config/automated_collection.json`이다.
설정 변경 뒤 재설치는 필요 없으며 다음 실행부터 적용된다.

## 장애별 복구

### 서버가 열리지 않음·중복 실행

1. `curl -s http://127.0.0.1:8787/api/health`를 확인한다.
2. 다른 프로세스가 8787을 점유하면 `lsof -nP -iTCP:8787 -sTCP:LISTEN`으로 식별한다.
3. 정상 KESCO 서버가 아니면 해당 프로세스를 사용자가 확인·종료한 뒤 다시 시작한다.
4. 같은 앱의 중복 시작은 `data/server.lock`이 막는다. 실행 중 프로세스를 강제 종료하지
   않은 상태에서 lock 파일 자체를 삭제해 우회하지 않는다.

### 네트워크·provider 수집 실패

1. `logs/collection.log`와 `/api/operations/status`의 `collection.latest`를 확인한다.
2. `lastSuccessful`과 기존 후보는 유지된다. 실패를 성공으로 바꾸거나 DB row를 삭제하지 않는다.
3. 네트워크가 회복되면 화면의 `오늘 기사 검색`으로 수동 재시도한다. 이미 수집 중이면
   `COLLECTION_ALREADY_RUNNING`이 반환되므로 기존 실행 완료를 기다린다.

### Ollama·AI 실패

1. health의 `error`와 `logs/ai.log`를 확인한다.
2. 기존 정상 AI 결과와 담당자 수정 요약은 그대로 사용한다.
3. Ollama 회복 뒤 담당자가 명시적으로 재분석한다. 자동 재분석하지 않는다.

### DB 무결성 실패·복구

1. launchd를 제거하거나 server agent를 bootout하고 8787 서버가 중지됐는지 확인한다.
2. `backups/db/`에서 복구 후보를 확인한다. 인자를 생략하면 최근 정상 백업을 선택한다.
3. `.venv/bin/python scripts/restore_database.py [백업.db]`를 실행한다.
4. 복구기는 선택 백업 검증, 현재 DB 안전 백업, 임시 복제 검증, 원자 교체를 수행한다.
5. 앱을 다시 시작하고 health와 operations status, 최종 report version을 확인한다.

복구 뒤에도 `backups/briefing/`과 `reports/`는 삭제하지 않는다. DB에 저장된 최종 snapshot과
저장 HTML이 다르면 DB snapshot으로 `/report/{date}`를 재생성할 수 있으므로 파일을 임의
수정하지 말고 차이를 기록한다.

## 재부팅 검증

재부팅 전 미선정 기사 메모와 중요 표시를 저장하고 DB 백업을 한 번 만든다. 재부팅 뒤 server
agent, health, operations status, 기존 메모·중요 표시, 최신 최종본, 다음 자동수집 실행을 순서대로
확인한다. Mac이 잠자기·종료였던 시간의 RSS는 소급 수집을 보장하지 않는다.
