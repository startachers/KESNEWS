# Phase 8 완료 보고 및 다음 작업 지시 — Phase 9

## Phase 8 완료 보고

작업본 편집 흐름과 CEO 최종 보고 흐름을 분리하고, 최종본을 불변 snapshot과 version별 HTML로 누적한다.

### 변경·신규 파일

- snapshot·HTML: `backend/app/services/reports/{snapshot,renderer,storage}.py`
- 저장·API: `backend/app/repositories/briefing_version_repository.py`, `backend/app/api/reports.py`
- 연결 변경: `backend/app/{main.py,api/{briefings,articles,exports,envelope}.py}`, `backend/app/repositories/briefing_repository.py`
- 백업: `backend/app/services/exports/{json_export,csv_export}.py`
- 프런트: `frontend/{index.html,css/app.css,js/{app.js,api/client.js,state/store.js,ui/renderers.js,features/{articles,collection,ai-analysis,data-io}.js}}`
- 테스트: `tests/integration/test_phase8_reports.py`, `tests/integration/test_exports.py`
- 회귀 기록: `docs/regression/PHASE8_2026-07-16.md`

### 구현 내용

- `finalize`는 `expectedRevision`을 검증하고 version N의 자족적인 JSON snapshot과 읽기 전용 HTML을 만든 뒤 작업본을 `final`로 잠근다.
- `reopen`은 기존 최종본을 보존한 채 작업본을 `draft`로 열며, 재확정하면 N+1을 추가한다.
- snapshot은 브리핑 필드, 선정 기사와 평가·메모, 선정 이슈 상태, 마지막 성공 AI run, `A01 → article_id → 기사 snapshot`을 보존한다.
- `/preview/{date}`는 현재 작업본, `/report/{date}`와 `?version=N`은 최종 snapshot을 편집 컨트롤 없이 렌더링한다. 저장 HTML이 없어도 DB snapshot으로 재생성한다.
- 최종 화면은 managementMessage, situationSummary, keyIssues, decisionPoints, actionItems, riskOutlook의 근거를 기사 anchor에 연결하고 stale AI 상태를 표시한다.
- 일반 `PUT`으로 `status=final`을 우회할 수 없으며 final 작업본의 편집과 수동 기사 추가를 거부한다.
- JSON 정식 백업 schemaVersion을 4로 올려 최종 version을 왕복한다. schemaVersion 1~3 import 호환을 유지하고 동일 version 내용 충돌은 replace로도 거부한다.
- JSON·CSV 내보내기는 `scope=working|latest-final|version:N`을 지원한다.
- 편집 화면에 미리보기·최종 확정·최종본 보기·수정 재개 제어를 추가하고, 확정 전 대기 중인 기사 메모와 스칼라 저장을 모두 완료한다.

### 검증 결과

- 자동: `.venv/bin/python -m pytest -q` 99건 통과, `.venv/bin/ruff check .` 통과, 전체 `node --check` 통과, `git diff --check` 통과
- 실제 로컬 HTTP: 작업본/최종본 200, 최종본 없는 404, 읽기 전용 HTML에 편집 요소 없음, 인쇄 CSS·버튼·선정 기사 표시 확인
- finalize → v1 → reopen → 수정 → v2 불변성, final mutation 거부, AI 근거 anchor, schemaVersion 4 최종 version 왕복과 충돌 거부를 확인했다.
- `legacy/kesco_media_briefing_original.html`과 사용자 소유 `.claude/`는 수정하지 않았다.

### 범위에서 제외한 항목

- scheduler·launchd·로그 회전: Phase 9
- `/api/settings`와 검색 요청 바디 축소: 기존 P4-001 후속 유지
- 세션 토큰 기반 API 인증: 별도 운영 보안 범위

---

## 다음 작업 — Phase 9: 자동화·운영 안정화

### 사전 확인

작업 시작 전 `docs/ARCHITECTURE.md` 15~17장과 Phase 9 정의, `docs/KNOWN_RISKS.md`의 미해소 항목을 읽는다.

### 작업 범위

- 운영 DB 백업·복구 절차와 보존 정책을 완성한다.
- Mac `launchd` 기반 자동 실행·수집 경로를 추가한다.
- 앱 중복 실행 방지, 로그 회전, 실패 상태 확인 경로를 완성한다.
- 1~2주 병행운영 체크리스트와 장애 복구 절차를 문서화한다.
- Phase 8의 snapshot·HTML·기존 수동 수정 보존 계약을 변경하지 않는다.

### 검증

- 재부팅·중복 실행·네트워크/AI 장애 복구
- 자동 수집 실패 시 마지막 정상 데이터 보존
- DB 백업 복구와 최종 snapshot/HTML 일치
- 로그 보존·회전과 운영자 오류 확인
- `python -m pytest -q`, `ruff check .`, 관련 수동 회귀
