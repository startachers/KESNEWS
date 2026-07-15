# Codex 다음 작업 지시 — Phase 0 완료 후 Phase 1

## 작업 범위

이번 작업은 기준선 고정과 프런트엔드 파일 분리만 수행한다. 백엔드, SQLite, 분류 개선, AI 근거 검증은 구현하지 않는다.

## 1. Phase 0

1. 현재 저장소와 `AGENTS.md`, `docs/API_DATA_CONTRACTS.md`, `docs/KNOWN_RISKS.md`를 읽는다.
2. `.gitignore`를 적용한다.
3. 모든 `.DS_Store`를 삭제한다.
4. `git status --short`에서 의도한 파일만 남는지 확인한다.
5. `legacy/kesco_media_briefing_original.html`의 hash를 기록한다.
6. `docs/MANUAL_REGRESSION_CHECKLIST.md`로 원본을 검증한다.
7. 브라우저 연결이 없으면 자동 검증으로 대체했다고 주장하지 말고, 수행하지 못한 항목을 명시한다.
8. 기존 위험은 `docs/KNOWN_RISKS.md`에만 기록하고 코드로 수정하지 않는다.
9. 최초 commit이 없으면 기준선 commit을 만든다.

권장 commit:

```text
docs: establish KESCO media briefing baseline and contracts
```

## 2. Phase 1

1. 원본 HTML은 수정하지 않는다.
2. 인라인 CSS를 `frontend/css/app.css`와 `frontend/css/print.css`로 분리한다.
3. 인라인 JavaScript를 ES Module로 분리한다.
4. RSS, localStorage, 위험도 계산, AI 호출의 동작 위치와 로직은 바꾸지 않는다.
5. 신규 dependency와 프레임워크를 추가하지 않는다.
6. 분리본 검증은 로컬 정적 서버로 수행한다. ES Module은 `file://`에서 로드되지 않으므로 저장소 루트에서 `python3 -m http.server 8000`을 실행하고 `http://127.0.0.1:8000/frontend/index.html`을 연다. 이 서버는 검증용이며 저장소에 코드를 추가하지 않는다.
7. AI 세션 토큰(meta 태그 또는 `#ai=` hash) 전달이 분리본에서 유지되는지 확인한다.
8. 원본과 분리본의 UI·동작을 비교한다.
9. 차이가 있으면 Phase 1 회귀만 수정한다.

## 완료 보고 형식

- 변경 파일
- 이동한 함수·상태
- 자동 검증 결과
- 수동 회귀 결과
- 수행하지 못한 검증
- 원본과의 차이
- `KNOWN_RISKS.md`에 남긴 후속 항목
- Git commit hash
