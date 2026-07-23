# 현재 작업 체크포인트

## 2026-07-23 완료 — 검색군 확장 + '이슈 기사 찾아보기'

기사 검색식을 22→25개로 확장하고(cyber_security·labor_safety·peer_agencies), 이 셋이
본 후보 풀에 편입되도록 `get_relevance`에 rank ⑧⑨⑩ 기준을 함께 추가했다(검색군만
늘리면 rank 99로 폐기되므로 관련도 기준 동반 확장이 필수).

공사와 무관해도 여러 매체가 크게 다룬 사건을 따로 보여주는 '이슈 기사 찾아보기' 버튼을
신설했다. 본 파이프라인(관련도·우선순위·브리핑)과 완전히 분리된다.

- 저장: 수집 시 관련도 미달로 제외된 기사를 `dropped_article_pool`(migration 0029)에 보관.
  collector가 `dropped_article_repository.replace_for_run`으로 보고일별 최신 실행분만 유지.
- 조회: `GET /api/collections/discovered-issues?report_date=`가 버튼 클릭 시에만 그 풀을
  느슨하게 클러스터링(`services/collection/dropped_issue.py`). 정책: 같은 사건 5건 이상만
  이슈로, 큰 순 상위 5개, 연예·스포츠 제외(정치·경제·사회 등은 포함).
- 프론트: 헤더 '이슈 기사 찾아보기' 버튼 + `discoveredIssuesOverlay` 패널,
  `features/discovered-issues.js`. app.js/app.css 캐시버스팅 20260723-30.
- 테스트: `tests/unit/test_dropped_issue.py`, `tests/integration/test_discovered_issues_api.py`.
- 운영 주의: 예전 설정 저장 이력(SQLite override)이 있으면 새 검색군 3개는 설정 초기화 후 반영.

## 2026-07-23 완료

CEO 브리핑 분석 페이지에 **정부부처 동향** 섹션을 신설했다. 기존 4개 섹션 중
④ 기타 동향을 없애고, 그 안의 비(非)정부 참고·모니터링 동향은 ③ 경영 참고사항으로
병합했다. 정부부처 기사는 새 ④ 정부부처 동향 전용 섹션으로 분리한다.

- 정부부처 판정: `article_selection.is_government_article` (출처 `governmentPressRelease`
  또는 정부 메시지 카테고리) — 프론트 정부부처 필터와 동일 집합, 결정론적.
- 선정 단계: 사용자가 정부부처 필터에서 직접 브리핑 체크(`included`)한 기사가 12건에
  보존되며, 추가참고 구간(rank 7~12)에 정부부처 최소 2건을 프롬프트로 우선 유도(후보
  부족 시 완화, 하드 검증 없음).
- 분석 단계: `build_evidence_input`가 `governmentSource` 플래그를 전달하고, 프롬프트가
  정부 기사를 OUT_OF_SCOPE여도 reference 등급 keyIssue로 정책 동향을 보존하도록 지시.
- 렌더 단계: `renderer._render_government_reference`가 스냅샷 `evidence` 맵으로
  keyIssue를 정부/비정부로 결정론적 분할. 담당자가 체크했으나 keyIssue로 안 잡힌 정부
  기사는 제목·출처 한 줄로 보강(WYSIWYG).
- 외부(GPT/Claude 바로가기) 평문 경로도 정합화: `EXTERNAL_ANALYSIS_PROMPT`의 ④를
  정부부처 동향으로 바꾸고, `content_from_plain_text`가 "정부부처 동향" 헤딩을 별도
  keyIssue(제목 마커 `GOVERNMENT_ISSUE_TITLE`)로 파싱한다. 평문 경로는 모든 evidence
  id를 붙이므로 렌더러는 evidence 교집합 대신 제목 마커로 ③/④를 구분한다. 프론트
  요약/편집 빌더(`setEditorContent`, `formatAiAnalysis`)도 같은 규칙으로 병합·분리한다.
- 테스트: `tests/unit/test_government_briefing_section.py`,
  `tests/integration/test_markdown_report_draft.py`(섹션 재편 반영)

## 2026-07-21 완료

AI 분석용 Markdown 정제와 선택 근거 유효성 검증, 관련기사 보강 검색에 이어
P4-001 검색 설정 단일 원본 전환을 완료했다.

- 검색 기본값: `config/collection_settings.json`
- 사용자 override: SQLite `settings.key=collection`
- API: `GET/PUT /api/settings`, `POST /api/settings/reset`
- 수동·자동 수집 요청: `report_date`, `lookback_hours`만 전달
- 구버전 요청 바디의 검색식·키워드·provider 설정은 무시
- 기존 localStorage 검색 설정은 서버 override가 없을 때 최초 1회 이전
- CSV 분류 한글 label은 서버 설정의 ID↔label 매핑으로 왕복

회귀 기록:

- `docs/regression/SELECTED_EVIDENCE_VALIDATION_2026-07-21.md`
- `docs/regression/SETTINGS_UNIFICATION_2026-07-21.md`

## 다음 작업

새 기능 범위는 아직 확정하지 않았다. 다음 변경 전에는 운영 화면에서 정부부처 필터로
기사를 브리핑 체크한 뒤 AI 선정·분석·미리보기까지 실제로 ④ 정부부처 동향 섹션이
의도대로 채워지는지 확인하고(NC-006 참조), 새 요구사항을 기존 리팩터링과 분리해
작업 지시로 확정한다.

## 계속 범위 밖

- `legacy/kesco_media_briefing_original.html` 수정
- 로그인·다중 사용자·클라우드·Docker 도입
- provider 자격정보를 설정 API 또는 브라우저에 노출
- 담당자 수동 수정·등급·근거 선택을 자동 재분석으로 덮어쓰기
