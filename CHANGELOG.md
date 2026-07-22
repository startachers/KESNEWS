# 설계 패키지 변경 이력

## v1.2

설계 검토에서 발견한 실행 격차와 계약 공백을 보완했다.

- `.gitignore`를 패키지에 포함 (문서상 "적용한다"만 있고 파일이 없었음)
- 루트의 중복 HTML 사본을 제거하고 `legacy/` 원본 단일 유지 원칙을 README에 명시
- Phase 1 분리본 검증 방법 확정: ES Module은 `file://`에서 로드되지 않으므로 로컬 정적 서버 사용, AI 세션 토큰 전달 확인 항목 추가
- `briefing_articles` row 생성 시점(첫 PATCH 시 upsert)과 후보 목록 조회 규칙 계약 추가 (2.4~2.5장)
- 기사 전체 재정렬 bulk mutation 계약 추가 (2.6장)
- `POST /api/collections` 요청 body와 보고일 귀속 규칙 추가 (3.5장)
- relevance 등급(direct/related/low)의 점수 경계 정의 (4.1장, `relevance_tiers`)
- 담당자 판정 수정(`assessment` PATCH)의 동시성·`manual_override` 규칙 추가 (4.5장)
- 이슈 `auto_status` 전이 규칙과 `spread_score` 초기 산식 정의 (6.5장, `spread_scoring`)
- JSON import 충돌 규칙과 `IMPORT_CONFLICT` 오류 코드 추가 (7.1장, 8장)
- 필수 제약에 `article_assessments.article_id` UNIQUE 추가
- Google 뉴스 중계 URL의 원문 해석 한계를 LEG-011로 등록

## v1.1

Codex 사전평가를 반영해 백엔드·DB 구현 전 계약을 확정했다.

- 보고일별 단일 작업본 + 불변 최종 snapshot 모델로 변경
- 날짜 기반 API의 작업본·최종본 선택 규칙 명시
- 기사 선택 해제를 DELETE가 아닌 PATCH로 확정
- 메모·중요 표시·숨김 상태 보존 계약 추가
- provider별 수집 실행과 article observation 모델 추가
- 관련도·심각도·확산도 점수 및 우선도 임계값 명시
- 예방·사고·감사 문맥 충돌 순서 명시
- 모든 AI 주장 필드에 근거 기사 ID schema 적용
- 재그룹화 preview/apply와 editor override 보존 규칙 추가
- 현행 HTML 위험 등록부와 Phase 0·1 수동 회귀 체크리스트 추가
- JSON은 정식 백업, CSV는 손실형 교환 형식으로 구분
