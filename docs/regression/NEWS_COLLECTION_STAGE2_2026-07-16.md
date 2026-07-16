# 기사 수집 설계 단계 2 회귀 기록 — 2026-07-16

검증 환경: macOS, Python 3.11+, Node.js, Chrome, `127.0.0.1:8787`

## 구현 범위

- 중대화재·정전 Sentinel, 연합뉴스 선행 판정, 공통 관련도 필터
- Sentinel·rank 1 보호 상한과 `collectionLimit` 기본값 400
- migration `0008`의 `article_assessments.incident_json`
- API·기사 카드 사고 배지, JSON schemaVersion 6·CSV 왕복
- 단계 3 허용목록과 단계 4 네이버 provider는 미구현

## `new_rules_news_clip.md` §17 결과

| 번호 | 결과 | 검증 |
|---|---|---|
| 5 | 통과 | rank 99인 연합뉴스 Sentinel 보존 단위 테스트 |
| 6 | 통과 | 상한보다 Sentinel·rank 1 우선 보존 단위 테스트 |
| 7 | 통과 | 수치 미상 중대화재와 정전의 nullable incident 테스트 |
| 8 | 통과 | 실제 사고 신호가 없는 계획정전 제외 테스트 |
| 9 | 통과 | 원인 미확인 화재 카드가 `원인 미상 화재`이고 `전기화재`가 아님을 화면 확인 |
| 17 | 통과 | JSON schemaVersion 6·이전 버전 호환, JSON·CSV 신규 필드 왕복 통합 테스트 |
| 18 | 통과 | 선택·해제, 중요 표시, 메모, AI 분석/요약, finalize 통합 회귀 및 화면 편집 확인 |

## 자동 검증

- `.venv/bin/python -m pytest -q`: 152 passed, 기존 deprecation warning 3건
- `.venv/bin/ruff check .`: 통과
- `find frontend -name '*.js' -print0 | xargs -0 -n1 node --check`: 통과
- `git diff --check`: 통과
- migration 전·후 기존 기사·평가 보존, provider 일부 실패 시 기존 후보·수동 상태 보존,
  외부 RSS·Ollama를 호출하지 않는 테스트를 포함했다.

## 수동 화면 회귀

- 임시 SQLite DB와 로컬 FastAPI 서버에서 사고 기사 1건으로 검증했다.
- `원인 미상 화재` 배지와 관련도 3 표시, 선택 해제·재선택, 중요 표시, 기사 메모,
  요약 직접 수정을 확인했다.
- 날짜를 변경했다가 복귀해 선택·중요·메모·요약이 복원됨을 확인했다.
- JSON·CSV 내보내기 성공 알림과 인쇄 미리보기 2페이지를 확인했다.
- 화면 로드와 조작 중 신규 오류 표시는 없었다. 브라우저 자동화 런타임 제약으로
  DevTools Console 로그를 직접 추출하지 못해 서버 응답과 화면 오류 표시로 대체 확인했다.

## 남은 위험

- NC-003: 단계 3 신뢰 언론사 허용목록·공식자료 예외·Google source 판별
- NC-004: 단계 4 네이버 뉴스 API provider
- P4-001: 검색 설정의 localStorage·자동수집 파일 이중 원본
