# 현행 HTML 위험 등록부

이 문서는 기존 단일 HTML의 알려진 위험을 기록한다. Phase 1은 파일 분리만 수행하므로 아래 로직을 임의로 수정하지 않는다. 각 항목은 지정 Phase에서 테스트와 함께 처리한다.

| ID | 현행 위험 | 영향 | 회귀 기준 | 수정 Phase |
|---|---|---|---|---|
| LEG-001 | 일부 provider만 성공하면 기존 자동 수집 기사가 새 성공 결과로 교체돼 빠질 수 있음 | 부분 장애 시 후보 기사 소실 | 부분 성공 시 현재 동작을 기록하고 데이터 손실 가능성을 문서화 | Phase 3에서 backend로 위치만 이전(동작 미수정, P3-003 참조), 실제 수정은 후속 Phase |
| LEG-002 | AI 응답의 `articleIds`가 실제 입력 ID인지 검증하지 않음 | 존재하지 않는 근거가 보고문에 표시될 수 있음 | 잘못된 A99 응답 fixture를 준비 | Phase 7 |
| LEG-003 | `decisionPoints`, `riskOutlook`, management message 등에 근거 ID 구조가 없음 | 분석·전망의 근거 추적 불완전 | 현행 출력 구조 보존 | Phase 7 |
| LEG-004 | JSON import가 action note, 일부 상태·설정·오류 이력 등을 완전 복원하지 않음 | 백업이라고 믿고 복구하면 내용 누락 | 현행 export→import 차이를 기록 | Phase 4 |
| LEG-005 | CSV export/import가 category·risk 등의 한글 label과 내부 enum을 완전 왕복하지 못함 | 재가져오기 시 분류 왜곡 | export→import 결과 비교 | Phase 4 |
| LEG-006 | CSV 셀의 spreadsheet formula 시작문자 escape가 없음 | Excel·Numbers에서 의도치 않은 수식 실행 가능 | `=1+1`, `@SUM(...)` fixture | Phase 4 |
| LEG-007 | 기사 선택 해제와 휴지통 삭제의 장기 보존 의미가 명확하지 않음 | 메모·중요 표시 손실 가능 | 현행 UI 동작 캡처 | Phase 4 |
| LEG-008 | 제목 키워드 점수로 예방·사고, 감사·감사패가 충돌할 수 있음 | 위험도·긍부정 오분류 | 필수 한국어 fixture | Phase 5 |
| LEG-009 | 유사 제목 병합 시 provider별 관측·실행 이력이 단일 article 객체에 축약됨 | 수집 경로 감사·장애 추적 불가 | duplicateSources 현행 값 기록 | Phase 3~4 |
| LEG-010 | 재군집화 모델이 아직 없어 향후 수동 이슈 편집 보호 계약이 필요함 | 자동 재분석이 담당자 편집을 덮을 위험 | API·DB 계약 선확정 | Phase 6 |
| LEG-011 | Google 뉴스 RSS의 기사 URL은 인코딩된 중계 주소여서 리다이렉트 추적 없이 원문 URL을 얻기 어려움 | canonical URL 기반 완전 중복 제거가 실패해 동일 기사가 중복 표시될 수 있음 | 중계 URL 기사 fixture로 현행 dedup 결과 기록. 원문 해석 실패 시 중계 URL을 canonical로 유지하고 제목 기반 dedup에 의존함을 명시 | Phase 3에서 backend 포팅과 함께 fixture 테스트 추가(`tests/unit/test_normalization.py`), 원문 URL 해석 자체는 미해결(P3-004 참조) |
| LEG-012 | 연합뉴스 전체 뉴스 RSS(`news.xml`)는 최신 120건만 제공해 실측 기준 약 4~5시간분만 담김. lookback 48시간을 채우지 못함 | 하루 1회 수집 시 연합뉴스 직접 피드의 대부분을 놓치고 Google 뉴스 검색 경로에 의존 | 수집 시점 피드의 실제 시간 범위를 collection run에 기록 | Phase 3에서는 동작만 backend로 이전(단일 피드 유지, P3-004 참조), 섹션별 피드 추가·`launchd` 주기 수집은 후속 Phase, Phase 9에서 주기 확정 |

## Phase 1 처리 원칙

- 위 항목을 코드에서 고치지 않는다.
- 원본과 분리본이 동일하게 동작하는지 확인한다.
- 차이를 발견하면 회귀 버그로 기록하고 Phase 1 안에서 원본 동작에 맞춘다.
- 명백한 데이터 손상 가능성도 Phase 1에서는 별도 승인 없이 로직 변경하지 않는다.

## Phase 2 이후 후속 항목

| ID | 후속 필요 사항 | 배경 | 처리 Phase |
|---|---|---|---|
| P2-001 | `/api/health`가 아직 공통 envelope(`{ok, data, error, meta}`)가 아니라 flat 응답이다 | `frontend/js/features/ai-analysis.js`의 `checkAiServer()`가 Phase 1에서 로직 변경 없이 그대로 이전됐으므로 flat 계약을 유지함(ARCHITECTURE.md 11장 vs 실제 프런트엔드 기대치 불일치) | envelope 전환은 `frontend/js/api/client.js` 도입 시점(Phase 3 이후)에 프런트엔드 호출부와 함께 변경 |
| P2-002 | `/api/health`에 DB 연결 상태 필드가 없다 | SQLite가 아직 없음(Phase 4). 존재하지 않는 값을 항상 `true`로 고정 보고하지 않기 위해 필드 자체를 생략함 | Phase 4에서 DB 연결 필드 추가 |
| P2-003 | `logs/app.log`에 크기 기반 로테이션이 없다 | Phase 2는 최소 로그만 요구. 장기 실행 시 로그 파일이 무한히 커질 수 있음 | Phase 9(운영 안정화)에서 회전 정책 추가 |
| P2-004 | `start_kesco_briefing.command`의 "이미 실행 중" 판정이 `GET /api/health` 200 응답 여부만 확인한다 | 동일 포트에 다른 프로세스가 우연히 떠 있어도 health 응답이 오면 우리 서버로 오인할 수 있음(가능성은 낮음) | 필요성이 확인되면 이후 Phase에서 프로세스 식별자 등 추가 검증 검토 |
| P2-005 | Ollama 조회 실패 사유가 `/api/health` 응답에 노출되지 않고 서버 로그에만 남는다(`error: null` 고정) | 앱 자체 상태와 Ollama 상태를 분리하라는 지침에 따름. 상세 실패 사유는 Phase 7(AI 분석 안정화)에서 필요성 재검토 | Phase 7 |

## Phase 3 이후 후속 항목

Phase 3에서 RSS/GDELT/기관 API 수집·정규화·중복 제거·분류를 `backend/app/services/`로 옮기고 프런트엔드의 CORS 프록시(`settings.proxy`)를 제거했다. `runSearch`의 오케스트레이션 로직(provider 동시 호출 → 실패 시 GDELT 보조 전환 → exclude/lookback 필터 → 1차 dedup → classify → 기존 기사 매칭 → manual 병합 → 2차 dedup → 정렬 → 상한 슬라이스)을 `POST /api/collections` 하나로 그대로 포팅했다(로직 변경 없음).

| ID | 후속 필요 사항 | 배경 | 처리 Phase |
|---|---|---|---|
| P3-001 | `POST /api/collections` 요청 바디가 최종 계약(`API_DATA_CONTRACTS.md` §3.5, `{report_date, lookback_hours}`만 받음)과 달리 검색식·키워드·lookback 등 현재 localStorage 설정 전체와 `existingArticles`를 그대로 실어 보낸다 | 설정이 아직 서버에 없다(Phase 4 `/api/settings` 대상). Phase 3 범위를 "localStorage 유지 가능"으로 한정한 REFACTORING_MAP §5에 따른 임시 절충 | Phase 4에서 설정이 서버로 이동하면 요청 바디를 최종 계약대로 축소 |
| P3-002 | `classifyArticle`/`getRelevance`/`relevanceSort`/`prioritySort`/`deduplicateDetailed` 로직이 backend(`POST /api/collections` 경로)와 frontend(`frontend/js/features/collection.js`, 수동 기사 추가·JSON 임포트·UI 정렬 경로)에 이중으로 존재한다 | 수동 기사 추가(`ui/dialogs.js`)와 JSON 임포트(`features/data-io.js`)는 네트워크 없이 즉시 동작해야 해서 이번 Phase 범위(RSS/GDELT 수집 이전)에 포함하지 않았다 | Phase 4에서 `/api/articles`·JSON 임포트가 서버로 옮겨질 때 통합하고 frontend 사본을 제거 |
| P3-003 | LEG-001(부분 provider 실패 시 기존 정상 기사가 이번 실행 결과로 통째 교체되어 소실될 수 있음)을 이번에 고치지 않고 현재 동작 그대로 backend로 이전했다 | 이번 작업 범위를 "RSS/GDELT 이전 + CORS 제거"로 최소화하기로 결정 | 후속 작업에서 stale 후보 보존·표시(UI 배지 포함)를 별도로 설계 |
| P3-004 | LEG-011(Google 뉴스 중계 URL은 canonical URL을 알 수 없어 제목 기반 fuzzy dedup에 의존)과 LEG-012(연합뉴스 `news.xml`이 최신 120건만 제공)는 여전히 미해결이며 동작을 그대로 이전했다 | 로직 변경 없이 언어만 이동하는 것이 이번 Phase의 원칙 | LEG-011/LEG-012에 기록된 처리 Phase(Phase 3 후속·Phase 9) 유지 |
| P3-005 | `settings.endpoint`(기관용 뉴스 API)는 사용자가 임의 URL을 입력할 수 있고 이제 서버가 그 URL을 직접 호출한다(SSRF 유사 위험) | 로컬 앱이고 세션 토큰 인증은 아직 어떤 API에도 실제로 연결돼 있지 않아(P2 이후 미구현) 이번 Phase에서 새 인증 계층을 추가하지 않았다 | Phase 7에서 세션 토큰 검증이 실제로 붙을 때 `/api/collections`도 함께 보호할지 재검토 |
