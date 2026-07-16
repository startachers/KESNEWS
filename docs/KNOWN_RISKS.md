# 현행 HTML 위험 등록부

이 문서는 기존 단일 HTML의 알려진 위험을 기록한다. Phase 1은 파일 분리만 수행하므로 아래 로직을 임의로 수정하지 않는다. 각 항목은 지정 Phase에서 테스트와 함께 처리한다.

| ID | 현행 위험 | 영향 | 회귀 기준 | 수정 Phase |
|---|---|---|---|---|
| LEG-001 | 일부 provider만 성공하면 기존 자동 수집 기사가 새 성공 결과로 교체돼 빠질 수 있음 | 부분 장애 시 후보 기사 소실 | 부분 성공 시 현재 동작을 기록하고 데이터 손실 가능성을 문서화 | **Phase 4에서 해소.** 수집은 append-only(articles/article_observations upsert)로 바뀌어 실패 provider의 과거 기사를 삭제하지 않는다. `GET /api/articles`가 `stale=true, staleReason=provider_failed`와 `meta.failedProviders`를 반환한다. `tests/integration/test_collection_pipeline.py::test_partial_failure_preserves_previously_collected_articles` |
| LEG-002 | AI 응답의 `articleIds`가 실제 입력 ID인지 검증하지 않음 | 존재하지 않는 근거가 보고문에 표시될 수 있음 | 잘못된 A99 응답 fixture를 준비 | **Phase 7에서 해소.** 실행별 `A01 → article_id` index를 `ai_runs.evidence_json`에 고정하고 모든 참조를 검증한다. A99가 교정 재시도 뒤에도 남으면 결과 전체를 거부한다. `tests/integration/test_ai_analysis_api.py::test_unknown_a99_after_correction_rejects_whole_result` |
| LEG-003 | `decisionPoints`, `riskOutlook`, management message 등에 근거 ID 구조가 없음 | 분석·전망의 근거 추적 불완전 | 현행 출력 구조 보존 | **Phase 7에서 해소.** managementMessage·situationSummary·keyIssues·decisionPoints·actionItems·riskOutlook를 근거 객체 schema로 통일하고 내용 있는 모든 주장에 근거를 강제한다. `tests/unit/test_ai_schemas.py` |
| LEG-004 | JSON import가 action note, 일부 상태·설정·오류 이력 등을 완전 복원하지 않음 | 백업이라고 믿고 복구하면 내용 누락 | 현행 export→import 차이를 기록 | **Phase 4에서 해소.** `GET/POST /api/exports/{date}.json`이 schemaVersion 포함 정식 백업이며 briefing 스칼라 필드·기사 선택/중요/메모를 왕복한다. AI 분석 원본 객체는 `ai_runs`가 없는 Phase 4 범위 밖(P4-002 참조). `tests/integration/test_exports.py::test_json_export_import_round_trip_preserves_selection_and_notes` |
| LEG-005 | CSV export/import가 category·risk 등의 한글 label과 내부 enum을 완전 왕복하지 못함 | 재가져오기 시 분류 왜곡 | export→import 결과 비교 | **Phase 4에서 해소.** `backend/app/services/exports/csv_export.py`의 `RISK_LABELS`/`SENTIMENT_LABELS` 양방향 매핑으로 위험도·정서는 완전 왕복한다. 분류(category)는 설정이 아직 서버에 없어(P4-001) 원시 값을 그대로 왕복(라벨 변환 없음). `tests/integration/test_exports.py::test_csv_export_import_round_trip_preserves_risk_and_selection` |
| LEG-006 | CSV 셀의 spreadsheet formula 시작문자 escape가 없음 | Excel·Numbers에서 의도치 않은 수식 실행 가능 | `=1+1`, `@SUM(...)` fixture | **Phase 4에서 해소.** `csv_export._escape_cell`이 `=`/`+`/`-`/`@` 시작 셀에 `'` 접두를 붙이고, import 시 `_unescape_cell`이 이를 되돌린다. `tests/integration/test_exports.py::test_csv_export_escapes_formula_prefixed_cells` |
| LEG-007 | 기사 선택 해제와 휴지통 삭제의 장기 보존 의미가 명확하지 않음 | 메모·중요 표시 손실 가능 | 현행 UI 동작 캡처 | **Phase 4에서 해소.** `briefing_articles`가 `selected`/`starred`/`note`/`dismissed`를 독립적으로 저장하고, UI의 "삭제" 버튼은 물리 삭제 대신 `dismissed=true` PATCH로 매핑돼 메모·중요 표시를 보존한다(`DELETE /api/briefings/{date}/articles/{id}` 자체를 두지 않음, API_DATA_CONTRACTS.md 2.3장). `tests/integration/test_api.py::test_patch_dismissed_normalizes_selected_to_false_and_preserves_note` |
| LEG-008 | 제목 키워드 점수로 예방·사고, 감사·감사패가 충돌할 수 있음 | 위험도·긍부정 오분류 | 필수 한국어 fixture | **Phase 5에서 해소.** 문장 단위 실제 발생 신호를 예방 문맥보다 우선하고, `감사패`/`감사 인사` 안의 모호한 토큰만 억제한다. `감사패 … 감사원 감사`처럼 구체 경영 리스크가 함께 있으면 후자는 유지한다. `tests/unit/test_classification.py`의 한국어 fixture 참조 |
| LEG-009 | 유사 제목 병합 시 provider별 관측·실행 이력이 단일 article 객체에 축약됨 | 수집 경로 감사·장애 추적 불가 | duplicateSources 현행 값 기록 | Phase 3~4 |
| LEG-010 | 재군집화 모델이 아직 없어 향후 수동 이슈 편집 보호 계약이 필요함 | 자동 재분석이 담당자 편집을 덮을 위험 | API·DB 계약 선확정 | **Phase 6에서 해소.** 군집 실행을 proposal/apply로 분리하고 `issues.editor_*`와 `issue_membership_overrides`를 자동 결과와 별도로 저장한다. apply는 editor 필드와 수동 add/remove를 유지하며 effective 값은 editor/override를 우선한다. `tests/integration/test_clustering_api.py::test_recluster_apply_preserves_editor_fields_and_membership_overrides` |
| LEG-011 | Google 뉴스 RSS의 기사 URL은 인코딩된 중계 주소여서 리다이렉트 추적 없이 원문 URL을 얻기 어려움 | canonical URL 기반 완전 중복 제거가 실패해 동일 기사가 중복 표시될 수 있음 | 중계 URL 기사 fixture로 현행 dedup 결과 기록. 원문 해석 실패 시 중계 URL을 canonical로 유지하고 제목 기반 dedup에 의존함을 명시 | Phase 3에서 backend 포팅과 함께 fixture 테스트 추가(`tests/unit/test_normalization.py`), 원문 URL 해석 자체는 미해결(P3-004 참조) |
| LEG-012 | 연합뉴스 전체 뉴스 RSS(`news.xml`)는 최신 120건만 제공해 실측 기준 약 4~5시간분만 담김. lookback 48시간을 채우지 못함 | 하루 1회 수집 시 연합뉴스 직접 피드의 대부분을 놓치고 Google 뉴스 검색 경로에 의존 | 수집 시점 피드의 실제 시간 범위를 collection run에 기록 | **Phase 9 운영 완화 완료.** `launchd` 자동수집을 2시간 간격으로 확정해 피드 실측 범위보다 짧게 호출한다. Mac이 잠자기·종료 상태였던 구간은 소급 보장하지 않으며 Google 뉴스 검색 경로를 함께 유지한다. 섹션 피드는 공식 한국어 URL을 확인하지 못해 추측 추가하지 않았다. |

## Phase 1 처리 원칙

- 위 항목을 코드에서 고치지 않는다.
- 원본과 분리본이 동일하게 동작하는지 확인한다.
- 차이를 발견하면 회귀 버그로 기록하고 Phase 1 안에서 원본 동작에 맞춘다.
- 명백한 데이터 손상 가능성도 Phase 1에서는 별도 승인 없이 로직 변경하지 않는다.

## Phase 2 이후 후속 항목

| ID | 후속 필요 사항 | 배경 | 처리 Phase |
|---|---|---|---|
| P2-001 | `/api/health`가 아직 공통 envelope(`{ok, data, error, meta}`)가 아니라 flat 응답이다 | `frontend/js/features/ai-analysis.js`의 `checkAiServer()`가 Phase 1에서 로직 변경 없이 그대로 이전됐으므로 flat 계약을 유지함(ARCHITECTURE.md 11장 vs 실제 프런트엔드 기대치 불일치) | envelope 전환은 `frontend/js/api/client.js` 도입 시점(Phase 3 이후)에 프런트엔드 호출부와 함께 변경 |
| P2-002 | `/api/health`에 DB 연결 상태 필드가 없다 | SQLite가 아직 없음(Phase 4). 존재하지 않는 값을 항상 `true`로 고정 보고하지 않기 위해 필드 자체를 생략함 | **Phase 4에서 해소.** `dbConnected` 필드 추가(`backend/app/main.py`) |
| P2-003 | `logs/app.log`에 크기 기반 로테이션이 없다 | Phase 2는 최소 로그만 요구. 장기 실행 시 로그 파일이 무한히 커질 수 있음 | **Phase 9에서 해소.** app/collection/ai 로그를 파일당 5 MiB, 과거 5개로 회전한다. `backend/app/core/logging.py`, `tests/integration/test_phase9_operations.py` |
| P2-004 | `start_kesco_briefing.command`의 "이미 실행 중" 판정이 `GET /api/health` 200 응답 여부만 확인한다 | 동일 포트에 다른 프로세스가 우연히 떠 있어도 health 응답이 오면 우리 서버로 오인할 수 있음(가능성은 낮음) | **Phase 9에서 해소.** health `service=kesco-media-briefing` 식별자를 확인하고, 다른 프로세스의 8787 점유는 `lsof` 확인 안내와 함께 실패한다. 별도로 `flock` 단일 인스턴스 잠금을 사용한다. |
| P2-005 | Ollama 조회 실패 사유가 `/api/health` 응답에 노출되지 않고 서버 로그에만 남는다(`error: null` 고정) | 앱 자체 상태와 Ollama 상태를 분리하라는 지침에 따름. 상세 실패 사유는 Phase 7(AI 분석 안정화)에서 필요성 재검토 | **Phase 7에서 해소.** 단일 Ollama client의 연결 오류를 health `error`와 AI 실행 실패 이력에 기록한다. 앱 health 자체의 `ok`는 DB/정적 앱 상태와 분리해 유지한다. |

## Phase 3 이후 후속 항목

Phase 3에서 RSS/GDELT/기관 API 수집·정규화·중복 제거·분류를 `backend/app/services/`로 옮기고 프런트엔드의 CORS 프록시(`settings.proxy`)를 제거했다. `runSearch`의 오케스트레이션 로직(provider 동시 호출 → 실패 시 GDELT 보조 전환 → exclude/lookback 필터 → 1차 dedup → classify → 기존 기사 매칭 → manual 병합 → 2차 dedup → 정렬 → 상한 슬라이스)을 `POST /api/collections` 하나로 그대로 포팅했다(로직 변경 없음).

| ID | 후속 필요 사항 | 배경 | 처리 Phase |
|---|---|---|---|
| P3-001 | `POST /api/collections` 요청 바디가 최종 계약(`API_DATA_CONTRACTS.md` §3.5, `{report_date, lookback_hours}`만 받음)과 달리 검색식·키워드·lookback 등 현재 localStorage 설정 전체와 `existingArticles`를 그대로 실어 보낸다 | 설정이 아직 서버에 없다(Phase 4 `/api/settings` 대상). Phase 3 범위를 "localStorage 유지 가능"으로 한정한 REFACTORING_MAP §5에 따른 임시 절충 | **부분 해소(Phase 4).** `existingArticles`는 제거했다 — 수집이 이제 DB에서 직접 매칭하므로 프런트가 병합용 상태를 보낼 필요가 없다(핵심 설계 변경, P3-002도 함께 해소). 검색식·키워드는 `/api/settings`가 아직 없어 요청 바디 유지를 그대로 결정(P4-001로 계승) |
| P3-002 | `classifyArticle`/`getRelevance`/`relevanceSort`/`prioritySort`/`deduplicateDetailed` 로직이 backend(`POST /api/collections` 경로)와 frontend(`frontend/js/features/collection.js`, 수동 기사 추가·JSON 임포트·UI 정렬 경로)에 이중으로 존재한다 | 수동 기사 추가(`ui/dialogs.js`)와 JSON 임포트(`features/data-io.js`)는 네트워크 없이 즉시 동작해야 해서 이번 Phase 범위(RSS/GDELT 수집 이전)에 포함하지 않았다 | **Phase 4에서 해소.** `POST /api/articles`(수동 추가)와 exports import가 서버로 이전되면서 frontend의 `classifyArticle`/`deduplicate*`/`sameArticle`/`mergeDuplicateArticles`/`articlePreference`/`bigramSimilarity`를 완전히 삭제했다. UI 정렬에 필요한 `getRelevance`/`relevanceSort`/`prioritySort`/`isYonhapArticle`/`normalizedArticleTitle`/`canonicalArticleUrl`(AI 입력 signature용)만 `collection.js`에 남겼다 |
| P3-003 | LEG-001(부분 provider 실패 시 기존 정상 기사가 이번 실행 결과로 통째 교체되어 소실될 수 있음)을 이번에 고치지 않고 현재 동작 그대로 backend로 이전했다 | 이번 작업 범위를 "RSS/GDELT 이전 + CORS 제거"로 최소화하기로 결정 | **Phase 4에서 해소.** LEG-001 항목 참조 |
| P3-004 | LEG-011(Google 뉴스 중계 URL은 canonical URL을 알 수 없어 제목 기반 fuzzy dedup에 의존)과 LEG-012(연합뉴스 `news.xml`이 최신 120건만 제공)는 여전히 미해결이며 동작을 그대로 이전했다 | 로직 변경 없이 언어만 이동하는 것이 이번 Phase의 원칙 | LEG-012는 Phase 9의 2시간 주기수집으로 운영 완화. LEG-011의 중계 URL 한계는 유지 |
| P3-005 | `settings.endpoint`(기관용 뉴스 API)는 사용자가 임의 URL을 입력할 수 있고 이제 서버가 그 URL을 직접 호출한다(SSRF 유사 위험) | 로컬 앱이고 세션 토큰 인증은 아직 어떤 API에도 실제로 연결돼 있지 않아(P2 이후 미구현) 이번 Phase에서 새 인증 계층을 추가하지 않았다 | Phase 7에서 세션 토큰 검증이 실제로 붙을 때 `/api/collections`도 함께 보호할지 재검토 |

## Phase 4 이후 후속 항목

Phase 4에서 SQLite migration(`backend/app/db/`), 작업본·기사 API(`briefings.py`/`articles.py`), 수집 결과 영속화(LEG-001 실제 수정), JSON/CSV exports(LEG-004~007 실제 수정), 프런트엔드 localStorage 제거를 완료했다. `article_assessments`/`briefing_versions`는 최소 컬럼·최소 조회만 구현했다(REFACTORING_MAP "다음 Phase 구조를 미리 만들지 않는다" 원칙).

| ID | 후속 필요 사항 | 배경 | 처리 Phase |
|---|---|---|---|
| P4-001 | 검색식·키워드(`queries`/`coreKeywords`/`riskKeywords`/`positiveKeywords`/`excludeKeywords`/`endpoint`)가 여전히 `POST /api/collections` 요청 바디로 전달되고 `settings` 테이블은 스키마만 있고 읽고 쓰는 코드가 없다 | `/api/settings` API 도입 자체가 Phase 4 체크포인트 3 지시서에서 범위 밖으로 명시됨. 기사 수집 설계 변경 단계 1에서 시작해 현재 21개 검색식이 localStorage 기본값과 `config/automated_collection.json`에 함께 복제돼 수동·자동 수집의 이중 설정 위험이 더 명확해졌다. | `/api/settings` 도입 Phase에서 `new_rules_news_clip.md` §3 검색식을 단일 원본으로 이관하고 요청 바디를 최종 계약(API_DATA_CONTRACTS.md §3.5)대로 축소 |
| P4-002 | AI 분석 결과(`managementMessage`/`keyIssues`/`decisionPoints`/`riskOutlook` 등 구조화 객체와 `summaryEvidenceMap`/`summaryCoverage`)는 서버에 저장되지 않는다. `briefings.situation_summary`(최종 텍스트)와 `ai_model`/`ai_generated_at`/`ai_input_signature`만 영속화되므로, 브라우저를 새로고침하면 텍스트 요약은 남지만 구조화 근거 데이터는 사라진다 | `ai_runs` 테이블이 아직 없다(Phase 7 대상). Phase 4 범위는 briefing/기사 편집 상태 영속화이지 AI 근거 schema가 아니다 | **Phase 7에서 해소.** `ai_runs`에 request/response/evidence/error를 저장하고 브리핑 조회와 JSON schemaVersion 3 백업에서 복원한다. `tests/integration/test_exports.py::test_json_schema_v3_round_trip_preserves_ai_run` |
| P4-003 | `article_assessments`에는 `auto_category`/`auto_risk`/`auto_risk_score`/`auto_sentiment`/`auto_reasons_json`만 있고 `final_*`/`manual_override`/`auto_relevance_score`/`auto_severity_score`/`auto_priority_score`는 없다 | **Phase 5에서 해소.** `0002_article_assessment_phase5.sql`로 전체 판정 필드를 추가하고, 시작 시 기존 Phase 4 판정행을 `rules-v2`로 backfill한다. 자동 upsert는 `final_*`를 갱신하지 않으며 PATCH로 모두 비울 때만 `manual_override=false`가 된다 | 완료 |
| P4-004 | JSON/CSV import(`briefing_repository.set_article_state`)는 대량 반영 시 `expectedRevision` 검증 없이 직접 `briefing_articles`를 덮어쓴다 | import 자체가 "가져오기 대상으로 전체 교체"라는 명시적 배타 동작이라(JSON은 `mode=replace` 확인 후, CSV는 손실형 병합) 단건 PATCH의 동시성 계약과는 성격이 다르다고 판단 | 다중 사용자·다중 탭 동시 import 시나리오가 실제로 필요해지면 재검토 |
| P4-005 | `DELETE /api/articles/{id}`의 "다른 보고일 참조 없음" 조건을 `briefing_articles`에 연결된 서로 다른 `briefing_id` 개수(1개 이하만 허용)로 근사 구현했다 | **Phase 6에서 후속 처리.** 기존 보고일 참조 조건에 더해 `issue_auto_articles` 또는 `issue_membership_overrides`가 기사를 참조하면 물리 삭제를 거부한다. 이슈에서 제거하려면 membership override를 사용한다. | 완료 |
| P4-006 | CSV export/import의 "분류(category)" 컬럼은 한글 라벨 변환 없이 내부 `category_hint` 원시값(`direct`/`safety` 등)을 그대로 왕복한다 | 카테고리 한글 라벨은 `settings.queries`(현재 요청 바디/미래 `/api/settings`)에서 오는데, CSV export/import는 그 설정을 참조하지 않기로 결정(P4-001과 연동) | `/api/settings` 도입 후 category label 매핑을 CSV export/import에도 반영할지 재검토 |

## Phase 8 이후 후속 항목

| ID | 후속 필요 사항 | 배경 | 처리 Phase |
|---|---|---|---|
| P8-001 | 브라우저의 `AbortController`는 HTTP 요청만 끊고 `asyncio.to_thread`의 Ollama 생성은 계속되어, 창을 닫은 뒤에도 31B가 GPU를 점유할 수 있었다 | 팬 지속·중복 요청·10분 이상 timeout, 기존 화면에는 취소 버튼 없음 | **Phase 9 선행 핫픽스에서 해소.** 취소 token이 스트리밍 HTTP 소켓을 직접 종료하고, 단일 실행·5분 제한·31B 16K context/2,048 출력 상한·구조화 schema·종료 후 unload를 적용했다. `tests/integration/test_ai_analysis_api.py::test_running_analysis_rejects_duplicate_and_can_be_cancelled`, `tests/unit/test_ollama_client.py::test_cancel_interrupts_connection_before_first_response` |

## 기사 수집 설계 변경 후속 항목

`new_rules_news_clip.md` §18의 단계 1~3은 2026-07-16에 완료했다.
아래 항목은 각 단계의 회귀가 아니라, 문서에서 분리 구현하도록 정한 후속 단계의 현재 위험이다.

| ID | 후속 필요 사항 | 현재 영향·근거 | 처리 단계 |
|---|---|---|---|
| NC-001 | 중대화재·정전 Sentinel과 `incident_json`이 없었다 | 수치가 없거나 원인이 확인되지 않은 중대 사고 속보가 관련도 필터에서 탈락하고, 사고 정보가 저장·표시·내보내기에 남지 않았다. | **단계 2에서 해소.** Sentinel을 관련도보다 먼저 판정하고 migration `0008`의 `incident_json`, 사고 배지, JSON schemaVersion 6·CSV 왕복을 구현했다. `tests/unit/test_incident_sentinel.py`, `tests/integration/test_exports.py` |
| NC-002 | `collectionLimit` 절단이 Sentinel·rank 1을 보호하지 않고 기본값도 200이었다 | 검색군 결과가 많으면 반드시 보존해야 할 기사가 단순 상한 절단에서 잘릴 수 있었다. | **단계 2에서 해소.** 보호 대상을 먼저 보존하고 나머지를 관련도순으로 채우며 API·프런트·자동수집 기본값을 400으로 맞췄다. `tests/unit/test_incident_sentinel.py::test_collection_limit_keeps_sentinel_and_rank_one_before_other_articles` |
| NC-003 | 신뢰 언론사 허용목록·공식자료 예외·Google `<source url>` 판별이 없었다 | 허용목록 밖 매체 저장과 출처 통계 부재 위험이 있었다. | **단계 3에서 해소.** migration `0009`와 `config/trusted_media.yaml`, 도메인 판별, Google source URL 추출, 공식자료 예외, 실행별 `source_filter_stats` 저장·API·화면 표시를 구현했다. 초기 20곳은 운영 결과를 반영해 주요 경제·지역 및 전기·에너지·소방안전 전문 매체를 포함한 50곳으로 현실화했고 포털·재배포처는 계속 제외한다. 전환 직후 발견된 기존 미판별 후보 노출도 자동 후보의 `publisher_allowed=true` 조회 조건으로 보완하되 담당자 상태가 있는 기사는 보존한다. `tests/unit/test_media.py`, `tests/integration/test_collection_pipeline.py` |
| NC-004 | 네이버 뉴스 API provider는 아직 없다 | `.env.example`에는 `NAVER_CLIENT_ID`/`NAVER_CLIENT_SECRET` 자리만 문서화됐으며 실행 코드, query 변환, 장애 fallback은 없다. | 단계 4에서 별도 구현. 자격정보는 프런트·내보내기·오류에 노출하지 않는다. |
| NC-005 | 정부부처(총리실·기후에너지환경부) 홈페이지 원문을 직접 수집하는 provider와, 사이트 개편으로 URL이 바뀌어도 같은 게시물로 병합하는 source_id 우선 매칭이 없었다 | 검색식 기반 수집만으로는 정책브리핑에 잘 안 걸리는 기관 원문(말씀자료·보도자료)을 놓칠 수 있고, `canonical_url`만으로 병합하면 게시물 URL이 바뀔 때(수정·개편) 중복 기사가 쌓인다 | **2026-07-16 구현.** `opm_press.py`(국무조정실, `articleNo` 기준)·`me_press.py`(기후에너지환경부, `boardId` 기준)를 추가하고 실제 목록 페이지 HTML로 파서를 검증했다. `find_matching_article`이 canonical URL보다 `(provider, source_id)` 완전일치를 먼저 확인하도록 바꿨고 migration `0010`으로 색인을 추가했다. `policy_briefing.py`(정책브리핑 보도자료 OpenAPI)는 엔드포인트만 확인되고 서비스키·정확한 응답 필드명은 미확인이라 방어적 다중 후보 파싱으로 구현했으며, 서비스키는 NC-004와 동일 원칙으로 요청 바디가 아닌 서버 환경변수 `POLICY_BRIEFING_SERVICE_KEY`로만 읽고 비어 있으면 자동으로 건너뛴다. 대통령실(`president.go.kr`)은 WAF가 비브라우저 요청을 차단해 직접 크롤링이 확인되지 않았고, 정책브리핑 API·Google RSS 기반 수집(및 기존 `official_source_exemptions`)에 계속 의존한다. `tests/unit/test_gov_adapters.py`, `tests/integration/test_collection_pipeline.py::test_source_id_match_survives_url_change_between_runs` |

P4-001의 검색 설정 이중 원본(localStorage와 `config/automated_collection.json`)은 단계 3 이후에도
유지된다. `/api/settings` 일원화는 단계 4와도 섞지 않고 별도 작업으로 남긴다.
