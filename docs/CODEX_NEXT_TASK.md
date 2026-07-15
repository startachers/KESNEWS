# 다음 작업 지시 — Phase 3 완료 후 Phase 4

## 사전 확인

Phase 0(기준선 커밋 `82a69a3`)·Phase 1(`frontend/` 분리, `bc08306`)·Phase 2(FastAPI 골격, `7acb1c2`)·Phase 3(수집 백엔드 이전, `177a124`)는 완료됐다. `legacy/kesco_media_briefing_original.html`은 여전히 회귀 기준이며 수정하지 않는다.

작업 시작 전 반드시 읽는다: `AGENTS.md`, `docs/ARCHITECTURE.md`(5장 목표 구조, 7장 도메인 모델, 8장 SQLite 스키마 원칙, 11장 API 계약, 19장 Phase 4 정의), `docs/API_DATA_CONTRACTS.md`(1~2장 작업본·기사 선택, 3장 수집 이력, 7~8장 JSON·CSV·오류코드), `docs/KNOWN_RISKS.md`(LEG-001·004~007, P2-002, P3-001~003).

Phase 3에서 `POST /api/collections`는 상태를 저장하지 않는(stateless) 순수 계산 API로 구현했다. 프런트가 매번 `existingArticles`(현재 localStorage 상태)를 통째로 보내 서버가 병합만 해주는 임시 구조다(P3-001). Phase 4는 이걸 실제 SQLite 영속화로 바꾼다.

## 작업 범위 — Phase 4만 수행한다

localStorage를 SQLite로 교체하고, 수집 이력을 실제로 저장하며, 부분 수집 실패 시 기존 후보를 보존한다(LEG-001 실제 수정). 이슈 군집화(`issues`, `cluster_runs`)·AI 근거 schema(`ai_runs` 검증)·재군집화는 이번 범위가 아니다(Phase 6·7). `article_assessments`는 테이블만 만들고 컬럼은 최소(자동 판정 없이 Phase 3 classify 결과를 그대로 옮기는 수준)로 둔다 — 점수식·hard floor·cap 정교화는 Phase 5.

**범위가 크므로 아래 체크포인트 순서로 진행하고, 한 세션에 다 끝내지 못하면 완료된 체크포인트까지 커밋하고 나머지를 후속 작업으로 남긴다.** 체크포인트 사이에 항상 `python -m pytest -q`가 통과하는 상태를 유지한다.

### 체크포인트 1 — DB 골격과 migration

- `backend/app/db/migrator.py`, `backend/app/db/migrations/0001_initial.sql`
- 최소 테이블(ARCHITECTURE.md 8장): `schema_migrations`, `articles`, `article_observations`, `article_assessments`, `briefings`, `briefing_versions`, `briefing_articles`, `collection_runs`, `collection_run_providers`, `settings`
  - `issues`, `issue_auto_articles`, `issue_membership_overrides`, `cluster_runs`, `briefing_issues`, `ai_runs`는 아직 만들지 않는다(Phase 6·7에서 실제로 필요할 때 추가 — REFACTORING_MAP "한 Phase에서 다음 Phase의 구조를 미리 대규모로 만들지 않는다").
- 필수 제약: `articles.content_key` UNIQUE, `article_assessments.article_id` UNIQUE, `briefings.report_date` UNIQUE, `briefing_versions(briefing_id, version)` UNIQUE, `briefing_articles(briefing_id, article_id)` UNIQUE. 시작 시 `PRAGMA foreign_keys = ON`, WAL 모드.
- `backend/app/repositories/database.py`: 연결 관리, migration 자동 적용. `data/kesco_media_briefing.db`는 `.gitignore`에 이미 포함(`data/`).
- migration 실행 전 자동 백업(파일 복사, `backups/`) — `docs/ARCHITECTURE.md` 17장 참고.

### 체크포인트 2 — 작업본·기사 API

- `backend/app/repositories/{article_repository,briefing_repository,briefing_version_repository}.py`
- `backend/app/api/{articles.py,briefings.py}.py`
- 구현 대상(API_DATA_CONTRACTS.md 1~2장):
  - `GET/PUT /api/briefings/{date}` — `expectedRevision` 낙관적 동시성(1.4장), 최초 생성은 `expectedRevision:0`
  - `PATCH /api/briefings/{date}/articles/{article_id}` — `selected`/`starred`/`note`/`dismissed`/`sort_order`, 첫 PATCH 시 upsert(2.4장), `dismissed=true`면 서버가 `selected=false`로 정규화
  - `PUT /api/briefings/{date}/article-order` — bulk 재정렬(2.6장)
  - `GET /api/articles?report_date=&include_dismissed=false` — 2.5장의 3가지 합집합 규칙
  - `POST /api/articles` — 수동 기사 추가(현재 `ui/dialogs.js`의 `addManualArticle`이 하는 일을 서버로)
  - `DELETE /api/articles/{article_id}?confirm=true` — 2.3장 조건(수동+미참조+confirm) 미충족 시 `409 ARTICLE_IN_USE`
- `PATCH /api/articles/{article_id}/assessment`는 Phase 5에서 판정 로직과 함께 만든다. 지금은 만들지 않는다.

### 체크포인트 3 — 수집 결과 영속화 + LEG-001

- `POST /api/collections`를 stateless 계산에서 실제 저장으로 바꾼다: `collection_runs`/`collection_run_providers`/`article_observations`/`articles` insert·upsert.
- `existingArticles`를 요청 바디로 받는 방식은 제거하고 서버가 DB에서 직접 조회한다(P3-001 해소). `queries`/`riskKeywords` 등 검색 설정은 이번엔 `settings` 테이블에서 읽어오거나(권장) 계속 요청 바디로 받을지 결정하고 이 문서 다음 버전 또는 KNOWN_RISKS에 결정 근거를 남긴다 — `/api/settings` API 자체를 새로 만드는 것은 이번 범위가 아니다.
- LEG-001 실제 수정: provider 일부 실패 시 성공한 provider의 observation만 upsert하고, 실패한 provider가 이전에 성공적으로 채운 기사 후보는 삭제하지 않는다. 검색 기간 안의 기존 기사는 `stale=true`, `staleReason=provider_failed`로 응답에 포함한다(API_DATA_CONTRACTS.md 3.4장). 프런트 UI에 stale 배지를 최소한으로 추가한다.
- `GET /api/collections/latest?report_date=`, `GET /api/collections/{collection_run_id}` 추가.

### 체크포인트 4 — localStorage 제거, JSON/CSV 왕복

- 프런트 `state/store.js`의 `loadDailyState`/`saveDailyState`/`loadSettings`(작업 데이터 부분)를 API 호출로 교체. 설정(queries/keywords 등)을 아직 `/api/settings`로 옮기지 않았다면 그 부분만 과도기적으로 localStorage에 남기고 KNOWN_RISKS에 기록해도 된다 — 업무 데이터(기사·선택 상태·요약)는 반드시 SQLite로 옮긴다.
- `GET/POST /api/exports/{date}.json` — schemaVersion, 7.1장 import 충돌 규칙(`409 IMPORT_CONFLICT`, `mode=replace`), 내보내기→가져오기→다시 내보내기 동등성 테스트.
- `GET/POST /api/exports/{date}.csv` — 7.2장, `=`/`+`/`-`/`@` 시작 셀 escape(LEG-006), "일부 필드만 포함" 표시.
- LEG-004(JSON 왕복 누락)·LEG-005(CSV enum 왕복)를 새 구현에서 실제로 고친다. 원본 HTML 동작을 그대로 베끼지 않는다 — 이번 Phase는 대상 위험을 "고치는" Phase다.

## API 오류 코드

API_DATA_CONTRACTS.md 8장의 최소 집합 중 이번 Phase에서 실제로 쓰는 것만 구현한다: `BRIEFING_NOT_FOUND`, `BRIEFING_REVISION_CONFLICT`, `BRIEFING_FINALIZED`(체크포인트 2에서 상태값만 저장, `finalize`/`reopen` route 자체는 Phase 8), `ARTICLE_NOT_FOUND`, `ARTICLE_IN_USE`, `COLLECTION_PARTIAL`, `COLLECTION_FAILED`, `IMPORT_SCHEMA_UNSUPPORTED`, `IMPORT_CONFLICT`. 응답은 Phase 3에서 이미 적용한 공통 envelope(`{ok, data, error, meta}`)을 그대로 따른다.

## 반드시 결정하고 지시서에 남길 사항

1. **검색 설정의 출처**(체크포인트 3): 요청 바디 유지 vs `settings` 테이블 도입. 어느 쪽이든 KNOWN_RISKS에 근거를 남긴다.
2. **`article_assessments`의 이번 범위**: Phase 3 `classify_article` 결과(risk/riskScore/sentiment/category)를 그대로 저장하는 컬럼만 두고 `auto_relevance_score`/`auto_severity_score`/`final_*`/`manual_override` 등 Phase 5 전용 필드는 만들지 말지, 만들되 비워둘지 결정한다. 만들지 않는 쪽을 권장한다("다음 Phase의 구조를 미리 만들지 않는다").
3. **`classifyArticle`/`getRelevance`/`relevanceSort`/`deduplicateDetailed`의 frontend 중복(P3-002)**: `POST /api/articles`(수동 추가)와 JSON 임포트가 서버 API로 옮겨지므로, 이 시점에 frontend의 해당 함수를 삭제할지 결정한다. UI 정렬(`articles.js`/`issues.js`)에는 여전히 `relevanceSort`/`prioritySort`가 필요하므로 전부 지울 수는 없다 — 어디까지 지우고 어디를 남길지 명시한다.

## 그 외 제약

- 새 런타임 의존성(ORM 등)을 추가하지 않는다. `sqlite3`(stdlib)로 직접 작성한 repository 계층을 유지한다(AGENTS.md 기술 기준).
- `expectedRevision` 동시성 체크는 실제 DB 트랜잭션으로 검증한다(read-then-check가 아니라 UPDATE ... WHERE revision=? 패턴 권장).
- 네트워크 없는 테스트는 외부 서비스에 접속하지 않는다 — DB 테스트는 임시 SQLite 파일이나 `:memory:`를 쓴다.
- 데이터 구조 변경에는 migration과 복구 방법이 있어야 한다.

## 검증

1. `python -m pytest -q`, `ruff check .`
2. `tests/integration/test_database_migrations.py`(신규): migration이 빈 DB에서 끝까지 적용되는지, 재적용해도 안전한지(idempotent).
3. `tests/integration/test_api.py`(신규 또는 확장): 작업본 생성→기사 PATCH→새로고침(재조회)까지 데이터가 보존되는지.
4. 수동: `./start_kesco_briefing.command` 실행 → 기사 선택·중요 표시·메모 저장 후 브라우저 새로고침(localStorage를 지워도) 상태가 유지되는지. `docs/MANUAL_REGRESSION_CHECKLIST.md` 4~6장 재확인.
5. 수행하지 못한 검증은 완료 보고에 명시한다.

## 완료 보고 형식

- 변경·신규 파일
- 완료한 체크포인트 / 남긴 체크포인트(사유 포함)
- 새 테이블 스키마 요약과 migration 파일 경로
- API 변경 목록(요청·응답 예시)
- 자동 검증 결과 / 수동 확인 결과 / 수행하지 못한 검증
- `KNOWN_RISKS.md`에 남긴 후속 항목
- Git commit hash
