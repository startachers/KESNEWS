# 현재 단일 HTML → 목표 모듈 대응표

- 설계 버전: 1.2
- 상세 계약: `docs/API_DATA_CONTRACTS.md`

이 문서는 `legacy/kesco_media_briefing_original.html`의 함수와 상태를 단계적으로 어디로 옮길지 정의한다.

## 1. 초기 분리 단계

Phase 1에서는 동작 위치만 분리하고 업무 로직을 백엔드로 옮기지 않는다.

| 현재 코드 | Phase 1 위치 |
|---|---|
| 전체 `<style>` | `frontend/css/app.css`, 인쇄 규칙은 `print.css` |
| `init`, `bindEvents` | `frontend/js/app.js` |
| `settings`, `state`, `filters` | `frontend/js/state/store.js` |
| `renderAll`, `renderHeader`, `renderMetrics` | `frontend/js/ui/renderers.js` |
| `renderArticles`, 기사 이벤트 | `frontend/js/features/articles.js` |
| `renderTopIssues` | `frontend/js/features/issues.js` |
| `renderSummary`, AI 상태 UI | `frontend/js/features/ai-analysis.js` |
| modal·toast | `frontend/js/ui/dialogs.js`, `notifications.js` |
| 날짜·문자·HTML helper | `frontend/js/utils/` |

## 2. 백엔드 이전 단계

| 현재 함수·상태 | 최종 위치 | 비고 |
|---|---|---|
| `runSearch` | `services/collection/collector.py` | 전체 pipeline orchestration. 성공 결과로 목록 전체를 교체하지 않고 observation을 누적 |
| `fetchQuery` | collector + provider adapter | provider 선택 |
| `fetchGoogleRss` | `services/collection/google_news.py` | CORS proxy 제거 |
| `fetchYonhapRss` | `services/collection/yonhap.py` | 서버에서 직접 호출 |
| `fetchGdeltCombined` | `services/collection/gdelt.py` | fallback provider |
| `parseRssItems` | provider parser | RawArticle 반환 |
| `fetchCustomEndpoint` | 별도 provider adapter | 필요할 때만 유지 |
| `cleanText` | `services/extraction/cleaner.py` | HTML 정제 |
| `normalizedArticleTitle` | `services/normalization/title.py` | 테스트 필수 |
| `canonicalArticleUrl` | `services/normalization/url.py` | 추적 query 제거 |
| `parseDate`, `parseGdeltDate` | `services/normalization/dates.py` | UTC 표준화 |
| `deduplicateDetailed` | `services/deduplication/service.py` | exact/fuzzy 분리 |
| `sameArticle` | deduplication exact/fuzzy | Issue 판정과 분리 |
| `mergeDuplicateArticles` | deduplication service + observation repository | 대표 Article은 병합하되 provider·collection run별 observation 보존 |
| `bigramSimilarity` | `services/deduplication/fuzzy.py` | 초기 알고리즘 |
| `classifyArticle` | `services/classification/service.py` | assessment 생성 |
| `inferCategory` | `services/classification/rule_engine.py` | config 기반 |
| `getRelevance` | classification service | 관련도 축 |
| `prioritySort` | `services/briefing/selection.py` | 최종값 기준 |
| `generateSummary` | `services/briefing/rule_summary.py` | AI 없는 기본 요약 |
| `checkAiServer` | `/api/health` + frontend API client | Ollama는 backend만 호출 |
| `generateAiManagementSummary` | `services/ai/analyzer.py` | 모든 주장 필드의 구조화 근거 schema와 ID 검증 |
| `formatAiAnalysis` | `services/briefing/report_builder.py` 또는 frontend formatter | 최종 표현 계층 |
| `getSummaryInputSignature` | backend AI service | DB에 저장 |
| `loadSettings` | settings repository | config+override 병합 |
| `loadDailyState`, `saveDailyState` | briefing repository | localStorage 제거 |
| `exportJson` | exports API | versioned 정식 백업 JSON, round-trip 검증 |
| `exportCsv` | exports API | 손실형 목록 교환 포맷, formula escape |
| `loadSample` | test fixture 또는 demo endpoint | 운영 코드와 분리 |

## 3. 상태 이동

| 현재 전역 상태 | 최종 위치 |
|---|---|
| `settings` | 서버 settings + 프런트 캐시 |
| `state.articles` | SQLite articles + briefing_articles |
| `state.summary` | briefings.situation_summary |
| `state.actionNote` | briefings.action_note |
| `state.aiAnalysis` | ai_runs.response_json |
| `state.errors`, `warnings` | collection_runs |
| `state.fetchedAt` | collection_runs.finished_at |
| `state.duplicatesRemoved` | collection_runs 통계 |
| `filters` | 프런트 UI state |
| `isSearching`, `isAnalyzingSummary` | 프런트 UI state + API 상태 |
| `aiServerState` | `/api/health` 응답 |

## 4. 반드시 분리할 개념

### 현재 `article.included`

최종 구조에서는 `briefing_articles.selected`다.

### 현재 `article.starred`

최종 구조에서는 `briefing_articles.starred`다.

### 현재 `article.note`

최종 구조에서는 `briefing_articles.note`다.

### 현재 `article.risk`

최종 구조에서는 자동값과 최종값을 분리한다.

```text
article_assessments.auto_priority
article_assessments.final_priority
```

### 현재 중복 제거

- 동일 기사: deduplication
- 같은 사건의 별도 기사: clustering

두 기능을 같은 함수로 처리하지 않는다.

## 5. Phase별 이동 원칙

### Phase 1

파일만 분리한다. 로직 변경 금지.

### Phase 2

FastAPI가 정적 파일과 health만 제공한다.

### Phase 3

수집·정규화·중복 제거를 backend로 옮긴다. localStorage는 아직 유지 가능하다.

### Phase 4

업무 데이터를 SQLite로 옮기고 localStorage를 제거한다.

### Phase 5 이후

판정 구조와 Issue 모델을 도입한다.

한 Phase에서 다음 Phase의 구조를 미리 대규모로 만들지 않는다.


## 6. 기사 선택·삭제 UI 이동 계약

| 현재 UI 동작 | 최종 API | 보존 규칙 |
|---|---|---|
| 선정 체크 | `PATCH /api/briefings/{date}/articles/{id}` `selected=true` | note·starred·dismissed 미지정 필드 유지 |
| 선정 해제 | 같은 PATCH `selected=false` | association row, note, starred 보존 |
| 중요 표시 | 같은 PATCH `starred=true/false` | selected 상태 유지 |
| 기사 메모 | 같은 PATCH `note=...` | selected·starred 상태 유지 |
| 휴지통 | 같은 PATCH `dismissed=true` | selected는 false로 정규화, note·starred 보존 |
| 숨김 복원 | 같은 PATCH `dismissed=false` | 이전 note·starred 복원 |
| 원본 물리 삭제 | `DELETE /api/articles/{id}?confirm=true` | 미참조 수동 기사만 허용 |

`DELETE /api/briefings/{date}/articles/{id}`는 구현하지 않는다.

## 7. 브리핑 상태 이동 계약

현재 `loadDailyState(date)`가 날짜별 객체 하나를 읽는 경험은 유지하되 DB에서는 다음처럼 분리한다.

```text
현재 날짜별 localStorage 객체
→ briefings: 날짜별 현재 작업본 1개
→ briefing_versions: 최종 확정 snapshot N개
```

- `GET /api/briefings/{date}`는 현재 작업본만 반환한다.
- 작업본의 `revision`과 최종 snapshot의 `version`을 구분한다.
- `/preview/{date}`는 작업본, `/report/{date}`는 최신 최종 version이다.

## 8. 중복·수집 이력 이동 계약

현재 `provider`, `duplicateSources`, `rawCollectedCount`, `errors`, `warnings`는 다음으로 이동한다.

| 현재 값 | 최종 위치 |
|---|---|
| 기사 `provider` | `article_observations.provider` |
| `duplicateSources` | 동일 `article_id`에 연결된 observations 집합 |
| `rawCollectedCount` | `collection_runs.raw_count` |
| provider별 성공·실패 | `collection_run_providers` |
| 병합 방법·유사도 | `article_observations.dedup_method`, `dedup_score` |
| 부분 실패 재사용 | `collection_runs.stale_reused_count`와 API stale 표시 |

## 9. AI 출력 이동 계약

현재 문자열·배열 출력은 다음 객체 schema로 바꾼다.

```text
managementMessage  → { text, articleIds }
situationSummary   → { text, articleIds }
decisionPoints[]   → { text, articleIds }
riskOutlook        → { text, articleIds, isInference }
```

`keyIssues`와 `actionItems`를 포함해 모든 주장 필드의 ID를 입력 evidence index와 대조한다. 검증 실패 결과는 화면 상태에 적용하지 않는다.

## 10. 재그룹화 이동 계약

자동 그룹과 담당자 편집을 다음처럼 분리한다.

```text
자동 제목·상태·우선도      issues.auto_*
담당자 제목·상태·우선도    issues.editor_*
자동 구성 기사             issue_auto_articles
담당자 추가·제외           issue_membership_overrides
```

재그룹화는 proposal을 만든 뒤 apply하며, editor 값과 수동 membership을 덮어쓰지 않는다.

## 11. 현행 위험과 Phase 경계

`docs/KNOWN_RISKS.md`를 따른다.

- Phase 1: 파일 분리만 수행, 위험 로직 수정 금지
- Phase 3: 부분 수집 실패와 provider observation 수정
- Phase 4: 선택 해제·version·JSON/CSV 왕복 수정
- Phase 5: 점수·임계값·예방/사고 충돌 수정
- Phase 6: 재그룹화 override 보호
- Phase 7: AI 전체 근거 schema 검증
