# 현재 작업 체크포인트

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

새 기능 범위는 아직 확정하지 않았다. 다음 변경 전에는 운영 화면에서 설정 저장·복원과
다음 자동수집 실행을 확인하고, 새 요구사항을 기존 리팩터링과 분리해 작업 지시로 확정한다.

## 계속 범위 밖

- `legacy/kesco_media_briefing_original.html` 수정
- 로그인·다중 사용자·클라우드·Docker 도입
- provider 자격정보를 설정 API 또는 브라우저에 노출
- 담당자 수동 수정·등급·근거 선택을 자동 재분석으로 덮어쓰기
