# 검색 설정 단일 원본 전환 회귀 기록 — 2026-07-21

## 범위

- `config/collection_settings.json`을 버전 관리 기본값으로 사용
- `GET/PUT/POST reset /api/settings`와 SQLite 사용자 override 구현
- 수동 화면과 2시간 자동수집의 요청 바디를 보고일·24시간 범위로 축소
- 기존 localStorage 검색 설정의 최초 1회 이전
- CSV 분류 ID와 설정 한글 label의 양방향 변환

## 보존·복구

- 설정 저장·초기화는 `settings.key=collection` row만 변경한다.
- 기사, provider observation, 기사 평가, 브리핑 선정·메모·중요 표시, 최종 snapshot은 변경하지 않는다.
- 복구는 화면의 기본값 복원 또는 `POST /api/settings/reset`으로 override를 삭제한다.
- 기존 Git 비추적 `config/automated_collection.json`은 삭제하지 않지만 더 이상 실행 입력으로 읽지 않는다.

## 검증 결과

- `python -m pytest -q`: **367 passed**, 기존 deprecation warning 3건
- `ruff check .`: 통과
- `frontend/`, `scripts/` JavaScript `node --check`: 통과
- `git diff --check`: 통과
- 임시 DB와 `?noauto` 화면에서 설정 modal의 22개 검색 그룹 조회, 핵심 키워드 변경·저장,
  modal 재진입 후 서버 저장값 유지와 모니터링 chip 반영을 확인했다.
- 설정 저장 과정에서 신규 JavaScript 오류가 없음을 Console에서 확인했다. 작업본 자동 생성 전
  briefing 404와 수집 이력 부재 400은 기존 초기 상태 응답이다.
- 기본값 복원은 destructive UI 조작 대신 `POST /api/settings/reset` 통합 테스트로 override 삭제와
  기본 설정 복귀를 검증했다.
- 전체 `MANUAL_REGRESSION_CHECKLIST.md` 중 기사 편집·AI·기상·인쇄 항목은 이번 설정 단일화 범위에서
  화면 변경이 없으며 기존 자동 회귀를 통과했다. 외부 provider 실수집은 `?noauto` 검증이라 실행하지 않았다.
