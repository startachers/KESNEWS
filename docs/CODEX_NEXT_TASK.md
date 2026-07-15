# Codex 다음 작업 지시 — Phase 1 완료 후 Phase 2

## 사전 확인

Phase 0(기준선 커밋 82a69a3)과 Phase 1(`frontend/` 분리)은 완료됐다. `legacy/kesco_media_briefing_original.html`은 여전히 회귀 기준이며 수정하지 않는다. 작업 시작 전 `AGENTS.md`, `docs/ARCHITECTURE.md`(특히 5장 목표 구조, 11장 API 계약, 16장 실행·배포 구조, 19장 Phase 2 정의), `docs/API_DATA_CONTRACTS.md`, `docs/KNOWN_RISKS.md`를 읽는다.

## 작업 범위 — Phase 2만 수행한다

FastAPI 골격만 세운다. 수집·정규화·중복제거·분류·AI 분석·SQLite는 옮기지 않는다(Phase 3 이후). `frontend/` 내부 로직도 바꾸지 않는다.

1. 정적 파일 제공: FastAPI가 `frontend/`를 서빙해 `http://127.0.0.1:8787/`로 열면 지금의 `frontend/index.html`이 그대로 뜬다.
2. `GET /api/health` 구현.
3. 원클릭 실행 스크립트(`setup_kesco_briefing.command`, `start_kesco_briefing.command`).
4. 최소 로그(`logs/app.log`).

완료 기준(ARCHITECTURE.md 19장): `.command` 실행으로 화면과 health가 열린다.

## 만들 파일 (필요한 것만, 미래 구조를 미리 만들지 않는다)

```text
pyproject.toml
backend/app/main.py
setup_kesco_briefing.command
start_kesco_briefing.command
```

`backend/app/api/`, `domain/`, `repositories/`, `services/`, `db/` 등 ARCHITECTURE.md 5장의 목표 트리는 아직 만들지 않는다. Phase 3 이후 실제로 그 계층이 필요해질 때 생성한다. `main.py` 하나에 정적 파일 마운트와 `/api/health` 라우트만 두면 된다.

## 반드시 결정하고 지시서에 남길 사항 — `/api/health` 응답 모양

두 계약이 서로 다르다는 점을 인지하고 작업한다.

- `ARCHITECTURE.md` 11장의 최종 목표는 공통 envelope `{ok, data, error, meta}`다.
- 그런데 **현재 `frontend/js/features/ai-analysis.js`의 `checkAiServer()`는 Phase 1에서 로직을 바꾸지 않았으므로**, 원본 그대로 flat 응답을 기대한다: `{ ok, models, defaultModel, error }`를 최상위에서 바로 읽는다(`data.ok`, `data.models`, `data.defaultModel`).

Phase 2에서 프런트엔드의 AI 호출 로직은 아직 옮기지 않으므로(그건 이후 Phase, `frontend/js/api/client.js` 도입 시점), **지금은 현재 프런트엔드가 실제로 기대하는 flat 응답 모양을 그대로 구현한다.** 공통 envelope 전환은 프런트엔드의 API 호출부를 함께 바꾸는 Phase에서 처리한다. 이 결정을 어기고 envelope로 감싸면 AI 상태 표시(`aiConnectionState`, 모델 드롭다운)가 조용히 깨진다.

`/api/health` 최소 구현 지침:

- `ok: true`, `models: []`, `defaultModel: ""`를 우선 반환해도 된다. Ollama가 로컬에서 떠 있으면 `http://127.0.0.1:11434/api/tags`를 조회해 `models`/`defaultModel`을 채우는 것은 선택사항이다.
- Ollama 조회가 실패해도 `/api/health` 자체는 `ok: true`를 반환한다(앱 자체는 정상이므로). Ollama 오프라인은 `models: []`로 표현한다.
- 실제 분석(`/api/analyze`)은 Phase 7 전까지 만들지 않는다.
- DB 연결 상태 필드는 아직 SQLite가 없으므로(Phase 4) 넣지 않거나 항상 `true`로 고정하지 않는다 — 존재하지 않는 값을 거짓으로 보고하지 않는다. 필드 자체를 생략하는 편이 안전하다.

## 그 외 제약

- 새 프레임워크·Docker·로그인·다중 사용자 기능을 추가하지 않는다(ARCHITECTURE.md 21장 금지 목록).
- Python 3.11 이상, FastAPI. 의존성은 `pyproject.toml`에 최소한으로(`fastapi`, `uvicorn` 정도).
- 기본 호스트 `127.0.0.1:8787` 고정.
- `start_kesco_briefing.command`는 이미 8787 포트에 정상 서버가 떠 있으면 새로 띄우지 않고 브라우저만 연다(ARCHITECTURE.md 15장 "앱 중복 실행").
- `.venv`, `__pycache__`, `logs/`는 `.gitignore`에 반영한다.

## 검증

1. `python -m pytest -q`, `ruff check .` (테스트가 아직 없으면 최소 헬스체크 테스트 하나는 추가한다).
2. `./start_kesco_briefing.command` 실행 → 브라우저가 `http://127.0.0.1:8787/`로 열리고 화면이 Phase 1 분리본과 동일하게 표시되는지 확인.
3. `curl http://127.0.0.1:8787/api/health`로 응답 모양이 위 flat 계약과 일치하는지 확인.
4. `docs/MANUAL_REGRESSION_CHECKLIST.md` 1~2장 재확인(이번엔 `http://127.0.0.1:8000/frontend/index.html` 대신 `http://127.0.0.1:8787/`로 접속해 비교).
5. 브라우저 연결 없이 자동 검증만으로 끝냈다면 그렇다고 명시하고, 사람이 직접 열어 확인해야 할 항목을 완료 보고에 남긴다.

## 완료 보고 형식

- 변경·신규 파일
- `/api/health` 응답 예시(JSON)
- 자동 검증 결과
- 수동 확인 결과
- 수행하지 못한 검증
- 원본(Phase 1 분리본)과의 차이
- `KNOWN_RISKS.md`에 남긴 후속 항목
- Git commit hash
