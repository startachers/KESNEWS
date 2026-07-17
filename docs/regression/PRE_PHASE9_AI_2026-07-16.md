# Phase 9 선행 AI 안정화 회귀 기록 — 2026-07-16

> 이 문서는 당시 16K context로 수행한 회귀 기록이다. 2026-07-17에 선정 기사 15건의 전문 입력에서
> 31B 출력이 중단된 사례를 확인해 운영 기본값은 64K로 변경했다.

- 대상: `gemma4:31b` 경영메시지 생성의 취소·중복·장시간 GPU 점유
- 범위: Phase 9 착수 전 독립 핫픽스
- 불변 조건: 마지막 정상 AI 결과, 담당자 수정 요약, Phase 8 최종 snapshot·HTML 보존

## 확인 결과

- [x] 앱 전체 동시 AI 분석 1건 제한
- [x] 실행 중 중복 요청 `AI_ALREADY_RUNNING` 거부
- [x] UI의 `AI 분석 취소` 버튼이 실제 Ollama 연결을 종료
- [x] 첫 응답 전 취소도 HTTP socket shutdown으로 즉시 중단
- [x] 취소 후 `ai_runs.status=failed`, `AI_CANCELLED` 기록
- [x] 취소 후 기존 요약·마지막 정상 결과 보존
- [x] 앱 재시작 시 고아 `running` 실행을 `AI_INTERRUPTED`로 복구
- [x] 총 실행시간 5분 제한
- [x] 31B context 16K, 출력 2,048 token 상한
- [x] thinking 비활성화·JSON schema structured output
- [x] 성공·실패·취소 뒤 Ollama 모델 메모리 해제

## 실제 31B 검증

운영 DB와 분리한 가상 기사 2건으로 `gemma4:31b`를 실행했다.

```text
결과: success
소요: 143.3초
schema 교정 재시도: 0회(첫 시도 성공)
근거: A01, A02 검증 통과
종료 후 ollama ps: 실행 모델 없음
```

이어 현재 2026-07-16 작업본의 선정 기사 6건을 읽기 전용 입력으로 사용해 DB에 결과를 적용하지 않고 완주 시험했다.

```text
결과: success
선정 기사: 6건
소요: 40.0초
schema 교정 재시도: 0회(첫 시도 성공)
managementMessage 근거: A01, A04, A05, A06, A03 검증 통과
종료 후 ollama ps: 실행 모델 없음
```

실제 브라우저에서 2026-07-16 작업본의 기존 요약을 유지한 채 분석을 시작하고 즉시 취소했다. 버튼이 생성 상태로 복귀했고 `AI_CANCELLED`가 표시됐으며, `ollama ps`가 빈 목록임을 확인했다.

## 설치 모델 5종 전체 검증

운영 DB를 변경하지 않는 동일한 가상 기사 2건으로 설치된 Gemma 모델 5종을 순차 실행했다. 모든 모델이 첫 시도에 JSON schema와 근거 기사 ID 검증을 통과했다.

| 모델 | context | 생성 결과 | 소요 | schema 교정 | 경영메시지 근거 |
|---|---:|---|---:|---:|---|
| `gemma4:e2b` | 65,536 | 성공 | 10.9초 | 0회 | `A01` |
| `gemma4:e4b` | 65,536 | 성공 | 17.3초 | 0회 | `A01`, `A02` |
| `gemma4:12b` | 65,536 | 성공 | 22.7초 | 0회 | `A01`, `A02` |
| `gemma4:26b` | 65,536 | 성공 | 19.7초 | 0회 | `A01`, `A02` |
| `gemma4:31b` | 16,384 | 성공 | 42.8초 | 0회 | `A01`, `A02` |

각 모델에 별도로 첫 응답 전 취소를 요청했다. 5종 모두 약 1초 안에 `AI_CANCELLED`로 종료됐고 오류는 없었다. 언로드 호출 직후 `ollama ps`에 모델이 잠시 표시될 수 있으나 수초 뒤 자동으로 사라졌으며, 전체 검증 종료 후 실행 모델 목록은 비어 있었다.

## 자동 검증

```text
.venv/bin/python -m pytest -q  → 104 passed
.venv/bin/ruff check .         → 통과
node --check (frontend/js 전체) → 통과
git diff --check               → 통과
```
