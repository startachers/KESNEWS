# 외부 AI 바로가기 회귀 결과 (2026-07-22)

## 변경 범위

- 오늘의 경영 분석 도구에 `ChatGPT 바로가기`, `Claude 바로가기` 추가
- 버튼 클릭 시 공통 CEO 경영 분석 프롬프트를 클립보드에 복사
- ChatGPT 또는 Claude 새 대화 화면 열기
- 팝업 차단, 클립보드 차단 상태를 오류 안내로 표시
- 외부 AI API 호출, API 키, Markdown 자동 생성·다운로드·첨부·전송은 추가하지 않음
- 기존 Markdown 생성과 외부 AI 결과 검증·CEO 보고 편집본 저장 로직은 변경하지 않음
- 사용자 소유 미추적 파일 `.claude/settings.json`은 변경하지 않음

## 자동 검증

- `node --check frontend/js/features/report-draft.js`: 통과
- `node --check frontend/js/app.js`: 통과
- `.venv/bin/python -m pytest tests/test_health.py -q`: 6건 통과
- `.venv/bin/python -m pytest -q`: 378건 통과
- `.venv/bin/ruff check .`: 통과
- `git diff --check`: 통과

## 화면·동작 회귀

운영 데이터와 분리한 임시 SQLite DB와 `?noauto` 화면을 Headless Chrome에서 확인했다.

- [x] 1440×1200 화면에서 두 바로가기 버튼이 기존 분석 도구와 충돌 없이 표시됨
- [x] ChatGPT 클릭 시 `https://chatgpt.com/` 열기와 분석 프롬프트 복사 확인
- [x] Claude 클릭 시 `https://claude.ai/new` 열기와 분석 프롬프트 복사 확인
- [x] 복사 프롬프트에 `① 오늘 한줄`부터 `④ 참고 동향`까지 출력 계약 포함
- [x] 정상 경로에서 공급자별 성공 안내 표시
- [x] 팝업 차단 시 사이트 직접 열기 안내와 오류 상태 표시
- [x] Clipboard API와 fallback 복사가 모두 차단되면 클립보드 권한 오류 표시
- [x] 버튼 클릭 과정에서 신규 JavaScript 예외 없음
- [x] 바로가기 함수가 기존 Markdown 생성 API를 호출하지 않음

## 수동 확인이 남은 항목

- 실제 사용자 계정으로 열린 ChatGPT·Claude에 사용자가 MD 파일을 직접 첨부하고 프롬프트를
  붙여넣는 외부 서비스 내부 흐름은 자동 전송을 금지한 범위이므로 수행하지 않았다.
- 기사 선택·해제, 중요 표시, 메모, 날짜 변경, JSON·CSV, 인쇄 등
  `docs/MANUAL_REGRESSION_CHECKLIST.md`의 비관련 전체 수동 항목은 이번 국소 변경에서 재실행하지 않았다.
  관련 백엔드·프런트엔드 회귀는 전체 pytest 378건으로 확인했다.

## 남은 위험

- 브라우저 또는 조직 보안정책이 팝업·클립보드를 차단할 수 있다. 이 경우 앱은 차단 상태를
  오류로 표시하며 사용자가 외부 서비스를 직접 열도록 안내한다.
- 외부 서비스 URL이나 화면 정책이 변경되면 바로가기 URL을 갱신해야 한다.
