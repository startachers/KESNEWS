# Phase 6 완료 보고 및 다음 작업 지시 — Phase 7

## Phase 6 완료 보고

Phase 5의 기사 판정 기반 위에 이슈 군집화와 재군집 proposal/apply 흐름을 추가했다.

### 변경·신규 파일

- migration: `backend/app/db/migrations/0003_issue_clustering_phase6.sql`
- 군집화: `backend/app/services/clustering/{__init__,service}.py`
- 저장·API: `backend/app/repositories/{cluster_run_repository,issue_repository}.py`, `backend/app/api/issues.py`
- 연결 변경: `backend/app/{main.py,api/{articles,briefings,envelope}.py,repositories/{article_repository,briefing_repository}.py}`
- 백업: `backend/app/services/exports/json_export.py`
- 테스트: `tests/unit/test_clustering.py`, `tests/integration/{test_clustering_api,test_database_migrations,test_exports}.py`

### 구현 내용

- `issues`, `issue_auto_articles`, `issue_membership_overrides`, `cluster_runs`, `briefing_issues`를 migration으로 추가했다. 원본 기사와 provider observation은 수정하지 않는다.
- 제목·설명 유사도, 제목 공통 토큰 guard, 보도시각을 이용한 결정론적 군집화를 구현했다. 기사 deduplication과 이슈 clustering은 별도 단계다.
- `issues.auto_*`와 `editor_*`를 분리하고 제목·상태·우선도 effective 값은 editor 값을 우선한다.
- `POST /api/cluster-runs`는 proposal과 create/merge/split/move diff만 생성한다. `POST /api/cluster-runs/{id}/apply`가 입력 signature와 최종확정 상태를 다시 검사한 뒤 적용한다.
- apply는 editor 제목·상태·우선도와 수동 add/remove membership을 보존한다. 자동 군집에서 사라졌지만 수동 편집이나 override가 남은 이슈는 삭제하지 않고 검토 대상으로 유지한다.
- 계약의 초기 산식으로 spread score와 issue priority를 계산하고 `new`, `expanding`, `ongoing`, `cooling`, `closed` 상태 전이를 지원한다.
- `GET /api/issues`, 이슈 PATCH, 브리핑 이슈 선정 PATCH를 추가했다. 기사 물리 삭제는 자동·수동 이슈 참조가 있으면 거부한다.
- JSON 정식 백업 schemaVersion을 2로 올려 이슈 snapshot과 membership override를 왕복하며, 기존 schemaVersion 1 import도 계속 허용한다.

### 검증 결과

- 자동: `.venv/bin/python -m pytest -q` 76건 통과, `.venv/bin/ruff check .` 통과, `git diff --check` 통과
- migration·repository·proposal/apply, 동일 사건 군집/별개 기사 비군집, stale proposal 거부, 최종확정 브리핑 적용 거부를 테스트했다.
- 재군집화 뒤 editor 필드와 수동 add/remove 보존, 이슈 참조 기사 삭제 거부, 이슈 JSON export/import 왕복을 테스트했다.
- 임시 DB의 실제 서버를 `127.0.0.1:8787`에서 열어 화면 렌더링과 정적 리소스 로드를 확인했다. 빈 임시 DB의 해당 보고일 GET 404 외 신규 JavaScript 예외는 없었다.
- Phase 6은 프런트 화면 구조를 바꾸지 않아 기존 기사 선택·메모·날짜·CSV·인쇄 흐름은 자동 API 회귀 테스트와 기존 화면 로드로 확인했다. 실제 인쇄 대화상자 조작은 수행하지 않았다.
- `legacy/kesco_media_briefing_original.html`과 사용자 소유의 추적되지 않은 `.claude/`는 수정하지 않았다.

### 범위에서 제외한 항목

- Ollama client 단일화와 AI 근거 schema·검증: Phase 7
- 읽기 전용 CEO 보고 route와 최종 snapshot 화면: Phase 8
- `/api/settings`와 검색 요청 바디 축소: 기존 P4-001 후속 유지

---

## 다음 작업 — Phase 7: AI 분석 안정화

### 사전 확인

작업 시작 전 `docs/API_DATA_CONTRACTS.md`의 AI 계약, `docs/ARCHITECTURE.md` 13장과 Phase 7 정의, `docs/KNOWN_RISKS.md` LEG-002·LEG-003 및 P4-002를 읽는다.

### 작업 범위

- Ollama 호출 경로를 백엔드의 단일 client/service로 통합하고 실행 상태를 `ai_runs`에 기록한다.
- 실행별 고정 근거 ID(`A01` 등)와 article ID 매핑을 `evidence_json`에 저장한다.
- managementMessage, situationSummary, keyIssues, decisionPoints, actionItems, riskOutlook의 모든 내용 있는 주장에 유효한 `articleIds`를 강제한다.
- 존재하지 않는 근거 ID나 schema 위반이 하나라도 있으면 결과 전체를 적용하지 않고 형식 교정 재시도는 최대 1회만 수행한다.
- 기사 선택·메모·모델 변경 시 기존 결과를 삭제하지 않고 stale로 표시한다. 담당자가 수정한 `ai-edited` 요약은 재분석으로 덮어쓰지 않는다.
- AI 실패 시 마지막 정상 결과와 현재 오류 상태를 함께 반환한다.
- Phase 8의 최종 보고 route·snapshot 화면은 미리 만들지 않는다.

### 검증

- AI schema와 모든 주장 필드 근거 필수 단위 테스트
- fake Ollama client의 정상 결과, 잘못된 `A99`, schema 오류, 1회 교정 재시도 통합 테스트
- stale signature와 담당자 수정 요약 보존 테스트
- Ollama 오프라인 시 마지막 정상 결과·현재 오류 동시 표시 테스트
- `python -m pytest -q`, `ruff check .`, 관련 수동 회귀
