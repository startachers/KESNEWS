# KESCO AI 소관·근거 검증 회귀 기록 — 2026-07-21

## 1. 문제 원인

기존 2단계 Gemma 분석은 근거 기사 ID, 숫자, 조사 중 원인의 확정형 변환, 일부 기관 역할 혼동을
검사했지만 건축·소방·전력계통과 KESCO 직접 업무를 구조적으로 구분하지 않았다. 이 때문에 모델이
유효한 기사 ID를 붙이기만 하면 비소관 요소를 공사 점검 과제로 확장하거나 법령·기준 변경을 내부
조치처럼 작성할 수 있었다.

이번 변경은 수집, 본문 정제, 1차 규칙 분류, 기사별 LLM 호출을 추가하거나 변경하지 않는다.
담당자가 최종 선택한 기사에 대해 실행되는 기존 Gemma 중간 분석과 최종 작성만 강화한다.

## 2. 변경 범위

- `config/kesco_jurisdiction.json`: 실제 프롬프트와 서버 검증이 함께 읽는 소관 정책
- `backend/app/services/ai/jurisdiction.py`: 정책 로더
- `backend/app/services/ai/schemas.py`: 소관·불확실성·전기 원인·조치 주체 schema
- `backend/app/services/ai/prompt_builder.py`, `config/briefing_style_guide.md`: 분석 순서와 금지 규칙
- `backend/app/services/ai/grounding.py`: 비소관·권한 초과·입력 외 개념·불확실성 검증
- `backend/app/services/ai/analyzer.py`, `backend/app/services/reports/renderer.py`,
  `backend/app/services/reports/report_draft.py`, `backend/app/services/exports/markdown_export.py`,
  `frontend/js/features/ai-analysis.js`, `frontend/js/features/report-draft.js`: ① 오늘 한줄, ② 언론 동향 분석, ③ 경영 참고사항,
  선택적 ④ 참고 동향 포맷
- API·아키텍처 계약과 관련 단위·통합 테스트

## 3. 소관 판정 구조

각 중간 분석과 핵심 이슈는 `certainty`, `electricalCauseStatus`, `kescoJurisdiction`,
`jurisdictionReason`, `excludedElements`, `actionLevel`, `evidenceQuotes`를 가진다. 실행 항목은 여기에
`evidence`, `uncertainty`, `ownerType`을 추가한다. `OUT_OF_SCOPE` 제언은 schema에서 거부하며,
최종 소관 등급이 검증된 중간 분석과 다르면 서버가 전체 결과를 적용하지 않는다.

## 4. 2026-07-21 변경 전·후 비교

운영 DB는 읽기 전용으로 확인했으며 최신 기존 성공 실행의 잘못된 문장은 다음과 같았다.

> 메자닌 구조 등 특수 물류시설의 점검 항목 세분화

기존 결과는 메자닌·가연물 문제를 공사 점검체계 재정비로 연결하고, 그리드코드의 현행 업무 반영,
SMR·AI 데이터센터 전용 설비 점검 역량 확보, 공사 내부 AI 서비스 운영까지 직접 과제로 확장했다.

변경 후 회귀 기준은 다음 문장이다.

> 현재 보도만으로 전기적 발화 원인이나 공사 검사체계의 미비를 판단하기 어렵다. 공식 조사 결과에서 전기적 요인이나 현행 전기설비 검사·점검의 사각지대가 확인되는 경우에 한해 관련 기준 보완 필요성을 검토할 수 있다.

서버 테스트에서 메자닌 점검 항목 세분화는 `OUT_OF_SCOPE_RECOMMENDATION`과
`UNCONFIRMED_ELECTRICAL_ACTION`으로 제거되고, 위 조건부 관계기관 후속 확인 문장은 통과한다.
그리드코드·AI 데이터센터·온사이트 발전·SMR은 기사에 실제 등장하더라도 직접 KESCO 조치가 아니라
`MONITORING`으로 제한한다. 입력에 없을 때 생성된 SMR·감지기 미작동 등의 동의 표현은
`UNSUPPORTED_CONCEPT`로 거부한다.

주의: 현재 운영 DB의 은마아파트 기사 본문에는 실제로 감지기 미작동 조사 내용이 있고, 선택된 다른
기사 본문에는 SMR, 18.4GW, 온사이트 발전 내용도 존재한다. 따라서 이 단어 자체를 무조건 삭제하지
않고, 연결된 기사 근거가 없거나 KESCO 직접 과제로 과장된 경우를 차단한다. 운영 DB와 저장 결과는
수정하지 않았다.

## 5. 자동 검증 결과

- `python -m pytest -q`: 378 passed
- `ruff check .`: 통과
- 대표 회귀: 물류센터 비소관 제언 차단, 은마아파트 입력 외 사고 세부사항·원인 확정 차단,
  그리드코드 직접 소관 과장 차단, BESS 인력·장비·교육 준비 검토 허용, AI 윤리 정책 모니터링과
  외부기관 직접 지시 차단
- JSON 왕복, 외부 분석 편집본, 최종 snapshot, 기상 보고, 기사 선택·메모 관련 전체 기존 테스트 통과

### 실제 gemma4:31b 확인

운영 DB의 실패 실행은 재시작 전 프로세스에서 구형 프롬프트
`phase7-management-message-weather-v1`을 사용했다. 31B는 교정 재시도에서도 무면허 배선공사,
감지기 미작동, 인명 피해를 직접 인과로 다시 작성했고 서버가 이를 정상 거부했다.

동일한 12개 기사 입력을 운영 DB 쓰기 없이 새 프롬프트로 재실행한 결과, 중간 분석과 최종 작성이
각 1회 교정된 뒤 약 15분 내 성공했다. 문제의 직접 인과 문장은 최종 결과에서 사라졌으며,
A06·A07을 검사체계 변경으로 확장한 중간 제언은 `UNCONFIRMED_ELECTRICAL_ACTION`으로 제거됐다.
확인 과정에서 기사 사실에 포함된 정부의 `의무화` 표현까지 권한 초과로 보던 오탐도 발견하여,
권한·직접 조치 검사는 기사 사실·근거 인용이 아니라 공사 해석·제언에만 적용하도록 좁혔다.

## 6. 수동 회귀 체크리스트 결과

- 코드·자동검증 확인: 레거시 HTML 미수정, 수집·분류·그룹화 미변경, JSON·CSV 및 저장 회귀 테스트 통과
- 보고 HTML 구조 확인: 최종 snapshot 통합 테스트에서 새 3개 필수 절과 조건부 참고 동향 확인
- 격리 기동 확인: `/tmp` 임시 DB와 `127.0.0.1:8790`에서 루트 화면, 브리핑 생성 API,
  미리보기 HTML 200 응답과 새 3개 필수 절을 확인한 뒤 서버 종료
- 미실행: 실제 브라우저 클릭, Console, 인쇄 미리보기, 실제 Ollama 품질 실행
- 사유: 인앱 브라우저 자동화 연결을 사용할 수 없었고 운영 DB를 변경하는 수동 조작은 수행하지 않음

## 7. 남은 한계

- 한국어 고유명사 전체를 일반 규칙만으로 완전 탐지할 수는 없다. 현재는 입력 외 숫자, 영문 약어,
  정책에 명시된 위험 개념과 소관·행동 조합을 결정적으로 검증한다.
- 실제 Gemma 출력 품질은 설치 모델 상태에 영향을 받는다. 위반 결과는 한 번 교정한 뒤에도 남으면
  적용하지 않지만, 적법한 문장의 표현 품질은 담당자 검토가 필요하다.
- 실제 브라우저와 Ollama를 이용한 최종 육안 확인은 후속 운영 검증으로 남는다.
