# Phase 5 완료 보고 및 다음 작업 지시 — Phase 6

## Phase 5 완료 보고

Phase 4의 SQLite 기반 위에 판정 로직 재구축을 완료했다.

### 변경·신규 파일

- migration: `backend/app/db/migrations/0002_article_assessment_phase5.sql`
- 판정: `backend/app/services/classification/{rule_engine,service}.py`
- 저장·API: `backend/app/repositories/{database,article_repository}.py`, `backend/app/api/articles.py`
- 수집·가져오기 연결: `backend/app/services/collection/collector.py`, `backend/app/services/exports/{json_export,csv_export}.py`
- 프런트 API client: `frontend/js/api/client.js`
- 테스트: `tests/unit/test_classification.py`, `tests/integration/{test_database_migrations,test_api}.py`

### 구현 내용

- `article_assessments`에 `auto_event_type`, 관련도·심각도·우선도 점수, `auto_priority`, `auto_tone`, `final_*`, `manual_override`를 추가했다.
- 앱 시작 시 migration 전 DB를 백업하고, 기존 Phase 4 판정행 중 새 우선도 값이 없는 행만 `rules-v2`로 backfill한다.
- 기사 우선도는 `0.55 × relevance + 0.45 × severity`로 계산하고 required/review/reference 임계값, event cap, low relevance cap, hard floor 순서로 적용한다.
- `auto_reasons_json`에 rule ID, 매칭 문자열, relevance tier, 점수 breakdown, 적용 cap·floor를 구조화해 저장한다.
- 예방 문구와 실제 사고를 문장 단위로 구분하고, 실제 발생이 있으면 accident/mixed를 유지한다. `감사패`·`감사 인사`의 모호한 감사 토큰만 억제한다.
- `PATCH /api/articles/{article_id}/assessment`는 `final_*`만 수정한다. 하나라도 있으면 `manual_override=true`, 모두 `null`이면 false로 돌아간다.
- 자동 재분류 upsert는 `final_*`를 갱신하지 않는다. 목록 응답은 auto/final/effective 판정을 함께 제공하고 기존 화면 호환 risk/sentiment 필드도 effective 값에 맞춰 유지한다.
- JSON 백업은 assessment 객체를 함께 왕복한다. CSV는 손실형 포맷 특성상 가져온 분류·위험도·정서를 담당자 최종값으로 보존한다.

### 검증 결과

- 자동: `.venv/bin/python -m pytest -q` 66건 통과, `.venv/bin/ruff check .` 통과, `git diff --check` 통과
- 실제 임시 서버: `/` 200, 수동 기사 추가, mixed/required 자동 판정, final priority/tone override, 목록 재조회 시 effective 값 반영, 모든 final 값 초기화 후 자동값 복귀 확인
- 프런트엔드: 변경 API client와 관련 ES module `node --check` 통과
- 브라우저 자동화 도구가 세션에 없어 실제 클릭 UI, Console, 인쇄 미리보기는 수행하지 못했다. Phase 5는 화면 구조를 변경하지 않았고 관련 API·정적 로드는 확인했다.
- `legacy/kesco_media_briefing_original.html`은 수정하지 않았다.

### 범위에서 제외한 항목

- 이슈 군집화·재군집화와 editor membership override: Phase 6
- AI 근거 schema와 `ai_runs`: Phase 7
- `/api/settings`와 검색 요청 바디 축소: 기존 P4-001 후속 유지

---

## 다음 작업 — Phase 6: 이슈 군집화

### 사전 확인

작업 시작 전 `docs/API_DATA_CONTRACTS.md` 6장, `docs/ARCHITECTURE.md` 7.3·7.4장과 Phase 6 정의, `docs/KNOWN_RISKS.md` LEG-010을 읽는다.

### 작업 범위

- `issues`, `issue_auto_articles`, `issue_membership_overrides`, `cluster_runs`와 필요한 proposal 저장 구조를 migration으로 추가한다.
- 동일 사건의 여러 기사를 원본 보존 상태로 묶되 deduplication과 clustering을 분리한다.
- 자동 `auto_*`와 담당자 `editor_*`를 분리하고 effective 값을 editor 우선으로 계산한다.
- 재군집화는 `POST /api/cluster-runs` proposal/diff 생성 후 `POST /api/cluster-runs/{id}/apply`로 적용한다.
- apply 시 editor 제목·상태·우선도와 수동 add/remove membership을 덮어쓰지 않는다.
- 신규·지속·확산 상태와 spread score는 계약의 초기 산식을 따른다.
- Phase 7의 AI schema나 Phase 8의 보고 화면은 미리 만들지 않는다.

### 검증

- migration·repository·proposal/apply API 테스트
- 같은 사건 fixture의 군집과 별개 기사 비군집 테스트
- 재군집화 후 editor 필드와 membership override 보존 테스트
- `python -m pytest -q`, `ruff check .`, 관련 수동 회귀
