# Phase 7 완료 보고 및 다음 작업 지시 — Phase 8

## Phase 7 완료 보고

Phase 6의 이슈 군집화 기반 위에 백엔드 단일 Ollama 분석 경로와 검증 가능한 AI 실행 이력을 추가했다.

### 변경·신규 파일

- migration: `backend/app/db/migrations/0004_ai_analysis_phase7.sql`
- AI 서비스: `backend/app/services/ai/{ollama_client,prompt_builder,schemas,analyzer}.py`
- 저장·API: `backend/app/repositories/ai_run_repository.py`, `backend/app/api/analysis.py`
- 연결 변경: `backend/app/{main.py,api/{briefings,articles,envelope}.py}`
- 프런트: `frontend/js/{api/client.js,state/store.js,features/{ai-analysis,articles}.js,app.js}`
- 백업: `backend/app/services/exports/json_export.py`
- 테스트: `tests/unit/test_ai_schemas.py`, `tests/integration/test_ai_analysis_api.py`

### 구현 내용

- Ollama tags와 generate 호출을 백엔드 단일 client로 통합했다. `POST /api/briefings/{date}/analyze`만 AI 분석을 수행한다.
- 실행 시작 전에 `ai_runs`에 모델, prompt version, 입력 signature, 요청 snapshot과 고정 `A01 → article_id` evidence index를 기록한다.
- Pydantic strict schema로 managementMessage, situationSummary, keyIssues, decisionPoints, actionItems, riskOutlook의 내용 있는 모든 주장에 근거를 강제한다. riskOutlook은 `isInference=true`만 허용한다.
- schema 오류·빈 근거·존재하지 않는 ID가 하나라도 있으면 결과 전체를 거부하며 형식 교정은 최대 1회만 재시도한다.
- 분석 중 revision·선정·메모가 바뀌면 결과를 적용하지 않는다. 선정·메모·모델 변화는 기존 성공 run을 삭제하지 않고 stale로 계산한다.
- `summary_mode=ai-edited`인 담당자 수정 요약은 성공적인 재분석에도 덮어쓰지 않는다.
- 실패 run과 마지막 성공 run을 함께 반환하고 브리핑 재조회 후에도 구조화 결과·오류를 복원한다.
- JSON 정식 백업 schemaVersion을 3으로 올려 AI run을 왕복하며 schemaVersion 1·2 import도 계속 허용한다.
- AI 근거로 사용된 수동 기사는 evidence 무결성을 위해 물리 삭제하지 못한다.

### 검증 결과

- 자동: `.venv/bin/python -m pytest -q` 94건 통과, `.venv/bin/ruff check .` 통과, `node --check` 통과, `git diff --check` 통과
- fake Ollama의 정상 결과, A99 교정 성공·최종 거부, schema 오류 1회 교정, stale, ai-edited 보존, Ollama offline 시 마지막 정상 결과·현재 오류 동시 반환을 확인했다.
- JSON schemaVersion 3 AI run export/import 왕복과 migration을 확인했다.
- 수동 화면 회귀 결과는 작업보고에 별도 기록한다.
- `legacy/kesco_media_briefing_original.html`과 사용자 소유의 추적되지 않은 `.claude/`는 수정하지 않았다.

### 범위에서 제외한 항목

- 읽기 전용 CEO 보고 route와 최종 snapshot 화면: Phase 8
- `/api/settings`와 검색 요청 바디 축소: 기존 P4-001 후속 유지
- 세션 토큰 기반 API 인증: 별도 운영 보안 범위

---

## 다음 작업 — Phase 8: CEO 보고 분리

### 사전 확인

작업 시작 전 `docs/API_DATA_CONTRACTS.md` 1장과 7장, `docs/ARCHITECTURE.md` 14장과 Phase 8 정의를 읽는다.

### 작업 범위

- 작업본 finalize/reopen과 불변 `briefing_versions` snapshot 누적을 완성한다.
- `/preview/{date}`는 현재 작업본, `/report/{date}`는 최신 또는 지정 최종 version을 읽기 전용으로 제공한다.
- CEO 보고 화면은 편집 컨트롤 없이 snapshot만 렌더링한다.
- AI 주장 근거 article ID와 기사 snapshot의 연결을 최종본에서도 보존한다.
- Phase 9의 scheduler·launchd·로그 회전은 미리 만들지 않는다.

### 검증

- finalize → version 1 → reopen → 수정 → version 2 불변성
- final 작업본 일반 mutation 거부
- 최신/지정 version route와 최종본 없는 404
- 읽기 전용 화면·인쇄 미리보기·AI 근거 표시
- `python -m pytest -q`, `ruff check .`, 관련 수동 회귀
