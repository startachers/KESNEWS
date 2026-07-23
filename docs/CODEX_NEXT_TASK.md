# 현재 작업 체크포인트

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
