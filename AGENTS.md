# AGENTS.md

## 프로젝트 목적

이 저장소는 로컬 Mac 한 대에서 사용하는 한국전기안전공사 CEO 일일 언론브리핑 웹앱이다. 기존 HTML의 기사 수집·선별·메모·Gemma 분석·인쇄 흐름을 보존하면서 HTML/CSS/JavaScript + FastAPI + SQLite + Ollama 구조로 단계적으로 전환한다.

## 문서 우선순위

1. `docs/API_DATA_CONTRACTS.md`
2. `docs/ARCHITECTURE.md`
3. `docs/REFACTORING_MAP.md`
4. 현재 Phase의 작업 지시

상위 문서와 충돌하는 임의 구현을 하지 않는다.

## 절대 원칙

- `legacy/kesco_media_briefing_original.html`은 회귀 비교 기준이다. 수정하지 않는다.
- 한 작업에서 리팩터링과 신규 기능을 동시에 수행하지 않는다.
- 현재 단계의 요구사항에 없는 프레임워크·클라우드·Docker·로그인·다중 사용자 기능을 추가하지 않는다.
- 프런트엔드는 화면 표시와 사용자 입력만 담당한다. 수집, 중복 제거, 분류, 이슈 군집화, AI 분석, 영속 저장은 백엔드에 둔다.
- 기사 원본, provider observation, 기사 평가, 브리핑 선정 상태를 같은 데이터로 덮어쓰지 않는다.
- 담당자 수동 수정과 수동 등급은 이후 자동 수집·재분석·재군집화로 덮어쓰지 않는다.
- AI 결과를 자동 확정하지 않는다. 근거 기사 ID가 없는 판단은 최종 보고에 반영하지 않는다.
- 오류를 성공처럼 숨기지 않는다. 마지막 정상 데이터와 현재 오류 상태를 함께 표시한다.
- 신규 운영 의존성은 필요성, 대안, 영향 범위를 먼저 설명한 뒤 추가한다.

## 확정 데이터 계약

- 보고일별 편집 작업본은 1개다. `briefings.report_date`는 UNIQUE다.
- 최종 보고 version은 `briefing_versions`의 불변 snapshot으로 누적한다.
- 작업본 mutation은 `expectedRevision`을 검증한다.
- 기사 선택 해제는 PATCH `selected=false`다. association row를 삭제하지 않는다.
- UI 휴지통은 PATCH `dismissed=true`다. 메모와 중요 표시를 보존한다.
- `DELETE /api/briefings/{date}/articles/{article_id}`를 만들지 않는다.
- provider 응답은 `article_observations`에 기록한 뒤 동일 기사에 연결한다.
- provider 일부 실패 시 기존 후보를 제거하지 않고 stale 상태로 보존한다.
- 관련도 점수만으로 `required`를 만들지 않는다. 점수식과 floor·cap은 계약 문서를 따른다.
- AI의 managementMessage, situationSummary, keyIssues, decisionPoints, actionItems, riskOutlook에 유효한 `articleIds`를 강제한다.
- 재군집화는 proposal/apply 두 단계이며 `editor_*`와 membership override를 덮어쓰지 않는다.
- JSON은 정식 백업이다. CSV는 완전 복원을 보장하지 않는다.

## Phase 1 특별 원칙

- `docs/KNOWN_RISKS.md`의 기존 위험을 고치지 않는다.
- 부분 수집 실패, AI 근거 검증, JSON·CSV 왕복 같은 로직은 그대로 둔다.
- 원본과 분리본의 동작이 다르면 Phase 1 회귀로 본다.
- `docs/MANUAL_REGRESSION_CHECKLIST.md`의 결과를 작업보고에 포함한다.

## 기술 기준

- 프런트엔드: 프레임워크 없는 HTML, CSS, ES Modules
- 백엔드: Python 3.11 이상, FastAPI
- 저장소: SQLite, 직접 작성한 repository 계층
- 로컬 AI: Ollama
- 기본 호스트: `127.0.0.1:8787`
- 업무 기준 시간대: `Asia/Seoul`
- API 날짜·시각: ISO 8601, 시각은 UTC 저장, 보고일은 서울 기준 날짜

## 작업 절차

1. 관련 코드와 기준 문서를 먼저 읽는다.
2. 현재 Git 상태와 추적되지 않은 파일을 확인한다.
3. 수정 범위와 변경하지 않을 범위를 짧게 정리한다.
4. 현재 단계에 필요한 최소 변경만 구현한다.
5. 관련 테스트를 추가하거나 갱신한다.
6. 테스트와 수동 회귀를 실행한다.
7. 변경 파일, 동작 변화, 테스트 결과, 남은 위험을 보고한다.

## 기본 검증 명령

Python 프로젝트가 생성된 이후:

```bash
python -m pytest -q
ruff check .
```

프런트엔드 구조를 변경한 경우:

- `docs/MANUAL_REGRESSION_CHECKLIST.md` 수행
- Console 신규 오류 확인
- 기사 선택·해제
- 중요 표시
- 기사 메모 저장
- 날짜 변경
- 요약 직접 수정
- JSON·CSV 내보내기
- 인쇄 미리보기

## 완료 정의

- 변경된 기능의 정상·실패 경로가 모두 확인됐다.
- 기존 수동 수정 데이터가 보존된다.
- 네트워크가 없는 테스트는 외부 서비스에 접속하지 않는다.
- 데이터 구조 변경에는 migration과 복구 방법이 있다.
- API·DB 구현은 `docs/API_DATA_CONTRACTS.md`의 테스트를 포함한다.
- `docs/ARCHITECTURE.md`와 구현이 달라졌다면 문서도 같은 작업에서 갱신한다.
