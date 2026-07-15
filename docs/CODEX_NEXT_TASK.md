# Phase 4 완료 보고 및 다음 작업 지시 — Phase 5

## Phase 4 완료 보고

Phase 0(`82a69a3`)·Phase 1(`bc08306`)·Phase 2(`7acb1c2`)·Phase 3(`177a124`)에 이어 Phase 4(SQLite 이전)를 4개 체크포인트 모두 완료했다.

### 변경·신규 파일

- DB 골격: `backend/app/db/migrator.py`, `backend/app/db/migrations/0001_initial.sql`, `backend/app/repositories/database.py`
- 작업본·기사 API: `backend/app/repositories/{article_repository,briefing_repository,briefing_version_repository}.py`, `backend/app/api/{articles,briefings,envelope}.py`
- 수집 영속화: `backend/app/repositories/run_repository.py`, `backend/app/services/collection/collector.py`(재작성), `backend/app/api/collections.py`(재작성), `backend/app/services/normalization/{content_key,dates}.py`
- exports: `backend/app/services/exports/{json_export,csv_export}.py`, `backend/app/api/exports.py`
- 프런트엔드: `frontend/js/api/client.js`(신규), `frontend/js/state/store.js`·`features/{articles,collection,data-io}.js`·`ui/dialogs.js` 재작성. `frontend/js/utils/csv.js` 삭제, `strings.js`의 `uid`/`csvCell` 삭제(죽은 코드 정리)
- 테스트: `tests/integration/{test_database_migrations,test_api,test_exports}.py`(신규), `test_collection_pipeline.py`(갱신)

### 새 테이블 스키마 요약

`schema_migrations`, `articles`, `article_observations`, `article_assessments`(최소 컬럼: auto_category/auto_risk/auto_risk_score/auto_sentiment/auto_reasons_json/classifier_version — final_*/manual_override 없음), `briefings`, `briefing_versions`(Phase 8 대비 최소 조회만), `briefing_articles`, `collection_runs`, `collection_run_providers`, `settings`(테이블만, 미사용). migration: `backend/app/db/migrations/0001_initial.sql`.

### API 변경 목록

- `GET/PUT /api/briefings/{date}`, `PATCH /api/briefings/{date}/articles/{article_id}`, `PUT /api/briefings/{date}/article-order`
- `GET/POST /api/articles`, `DELETE /api/articles/{id}?confirm=true`
- `POST /api/collections`(요청에서 `existingArticles` 제거), `GET /api/collections/latest?report_date=`, `GET /api/collections/{id}`
- `GET/POST /api/exports/{date}.json`, `GET/POST /api/exports/{date}.csv`
- `GET /api/health`에 `dbConnected` 필드 추가

### 핵심 설계 결정

수집 실행(`POST /api/collections`)은 더 이상 `briefing_articles`(선택/중요/메모)를 건드리지 않는다. 그 상태는 DB에 독립적으로 저장되므로 재수집 시 `existingArticles` 병합이 불필요해졌다(P3-001/002 해소). UI의 "삭제"는 물리 삭제가 아니라 `dismissed=true` PATCH로 매핑해 메모·중요 표시를 보존한다(LEG-007 해소).

### 검증 결과

- 자동: `python -m pytest -q` 56건 통과, `ruff check .` 통과
- 수동(Playwright 헤드리스 브라우저로 실제 구동): 수동 기사 추가 → 중요 표시 → 메모 작성 → `localStorage.clear()` → 새로고침 후 선택·중요·메모 상태 보존 확인, 선택 해제 후 휴지통 이동(기본 목록에서 숨김) 확인, JSON/CSV 내보내기 다운로드 확인. 브라우저 console 오류 없음
- 수행하지 못한 검증: `docs/MANUAL_REGRESSION_CHECKLIST.md`의 전체 항목(인쇄 미리보기, AI 분석 흐름 등)은 사람이 직접 눈으로 보는 회귀까지는 완료하지 못했다. Ollama 연동 자체(AI 분석 생성)는 이번 Phase 범위가 아니라 별도로 확인하지 않았다

### 남긴 후속 항목

`docs/KNOWN_RISKS.md`의 "Phase 4 이후 후속 항목"(P4-001~006) 참고. 요약: 검색 설정은 여전히 요청 바디 유지(`/api/settings` 도입 시 재검토), AI 분석 구조화 결과는 `ai_runs`가 없어 미영속(Phase 7), `article_assessments`는 최소 컬럼만(Phase 5에서 확장), CSV의 category 컬럼은 라벨 변환 없이 원시값 왕복.

### Git commit

`7fc1f71`(체크포인트1) → `a4dd02f`(체크포인트2) → `f8b079f`(체크포인트3) → `4743471`(체크포인트4 백엔드) → `e17708e`(체크포인트4 프런트엔드)

---

## 다음 작업 — Phase 5: 판정 로직 재구축

## 사전 확인

작업 시작 전 반드시 읽는다: `AGENTS.md`, `docs/ARCHITECTURE.md`(19장 Phase 5 정의, 7.2 ArticleAssessment 전체 필드), `docs/API_DATA_CONTRACTS.md`(4장 판정 점수·임계값·규칙 충돌 전체), `docs/KNOWN_RISKS.md`(LEG-008, P4-003).

## 작업 범위

Phase 4는 `article_assessments`에 자동 판정 최소 컬럼(`auto_category`/`auto_risk`/`auto_risk_score`/`auto_sentiment`/`auto_reasons_json`)만 두었다. Phase 5는 다음을 도입한다.

- `final_category`/`final_event_type`/`final_priority`/`final_tone`/`manual_override`/`classifier_version` 등 담당자 최종값 컬럼 추가(migration `0002_*.sql`)
- 관련도·심각도·우선도 점수를 분리(API_DATA_CONTRACTS.md 4.1~4.2장)하고 `auto_relevance_score`/`auto_severity_score`/`auto_priority_score`/`auto_priority` 도입
- required/review 임계값과 hard floor·cap(4.3장), 문맥 판정 순서(예방/사고/감사 충돌, 4.4장)
- `PATCH /api/articles/{article_id}/assessment` 구현(Phase 4에서 의도적으로 보류)
- 담당자 수동 등급 수정 시 이후 자동 재분석이 덮어쓰지 않는 보호 규칙(4.5장, `manual_override`)
- LEG-008(제목 키워드 점수 충돌) 실제 수정과 관련 fixture

이슈 군집화·재군집화(`issues`/`cluster_runs` 등)와 AI 근거 schema는 Phase 6·7 범위이며 Phase 5에서 손대지 않는다(REFACTORING_MAP "한 Phase에서 다음 Phase의 구조를 미리 만들지 않는다" 원칙 유지).

## 검증

`python -m pytest -q`, `ruff check .`, 새 migration에 대한 `test_database_migrations.py` 확장, `PATCH .../assessment` API 테스트, MANUAL_REGRESSION_CHECKLIST.md 관련 항목 확인.
