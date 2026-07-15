# KESCO Media Briefing 프로젝트 설계 패키지

- 설계 버전: 1.2
- 운영 기준: 로컬 Mac 단독 사용
- 구현 방식: 기존 HTML을 보존한 단계적 전환

이 폴더는 한국전기안전공사 CEO 일일 언론브리핑 로컬 웹앱의 기준 설계와 Codex 작업 규칙이다.

## 먼저 읽을 파일

1. `AGENTS.md` — Codex가 모든 작업에서 지켜야 할 저장소 규칙
2. `docs/API_DATA_CONTRACTS.md` — 백엔드·DB 구현 전 확정 계약
3. `docs/ARCHITECTURE.md` — 최종 목표 구조, 데이터 모델, API, 모듈 책임
4. `docs/KNOWN_RISKS.md` — 현행 HTML의 알려진 위험과 수정 Phase
5. `docs/MANUAL_REGRESSION_CHECKLIST.md` — Phase 0·1 수동 검증표
6. `docs/REFACTORING_MAP.md` — 단일 HTML 코드를 새 구조로 옮기는 대응표
7. `docs/CODEX_NEXT_TASK.md` — 그대로 전달할 다음 작업 지시
8. `config/*.example.yaml` — 버전 관리할 업무 규칙 예시
9. `legacy/kesco_media_briefing_original.html` — 회귀 비교 기준 원본

`API_DATA_CONTRACTS.md`와 다른 문서가 충돌하면 API·데이터 계약이 우선한다.

## 적용 방법

프로젝트 저장소 루트에 이 폴더의 내용을 복사한다. 기존 HTML은 `legacy/kesco_media_briefing_original.html` 한 파일만 기준 원본으로 유지하고 수정하지 않는다. 저장소 루트나 다른 위치에 동일 HTML 사본을 두지 않는다. Phase 1 분리 작업은 이 legacy 원본을 읽기 전용 입력으로 삼아 `frontend/`에 새 파일을 만든다.

## 실제 작업 순서

### 1. 추적 제외 파일 정리

```bash
cd /Users/kesco/KESNEWS
find . -name .DS_Store -delete
```

`.gitignore`를 적용한 뒤 다음을 확인한다.

```bash
git status --short
```

`.DS_Store`, DB, 로그, 백업, 보고서가 추적 목록에 나타나면 먼저 정리한다.

### 2. 원본 실행과 수동 기준선 기록

`docs/MANUAL_REGRESSION_CHECKLIST.md`를 사용해 원본을 직접 실행한다. Codex 세션에 브라우저 연결이 없으면 사용자가 Chrome에서 확인하고 결과를 체크리스트에 기록한다.

현재 HTML의 알려진 결함은 `docs/KNOWN_RISKS.md`에 이미 등록돼 있다. Phase 1에서 이를 고치지 않는다.

### 3. 최초 Git commit

저장소가 아직 Git 저장소가 아니라면 한 번만 실행한다.

```bash
git init
```

의도한 파일만 확인한 뒤 커밋한다.

```bash
git add .
git commit -m "docs: KESCO 언론브리핑 기준선과 설계 계약 추가"
```

### 4. Phase 1 실행

Phase 1은 다음만 수행한다.

1. CSS 분리
2. JavaScript ES Module 분리
3. 화면·기능 변경 금지
4. 원본과 분리본 수동 회귀 비교
5. 회귀가 없을 때 commit

FastAPI, SQLite, 분류 개선, AI 근거 검증은 Phase 1에 포함하지 않는다.

## 백엔드 구현 전 필수 확인

다음 계약이 구현과 테스트에 반영돼야 한다.

- 날짜별 브리핑은 단일 작업본이며 최종본은 `briefing_versions` snapshot이다.
- 선택 해제는 DELETE가 아니라 `selected=false` PATCH다.
- 메모·중요 표시·숨김 상태를 보존한다.
- provider별 수집 실행과 모든 observation을 기록한다.
- 부분 수집 실패가 기존 자동 기사 후보를 제거하지 않는다.
- 관련도·심각도·확산도와 우선도 임계값을 분리한다.
- AI의 모든 주장 필드에 유효한 근거 기사 ID가 필요하다.
- 재군집화는 proposal/apply 방식이며 담당자 override를 덮어쓰지 않는다.
- JSON은 정식 백업, CSV는 손실형 목록 교환 형식이다.
