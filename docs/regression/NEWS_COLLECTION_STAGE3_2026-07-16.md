# 기사 수집 설계 변경 단계 3 회귀 기록

- 검증일: 2026-07-16 (Asia/Seoul)
- 범위: 신뢰 언론사 허용목록, 공식자료 예외, Google `<source url>`,
  `source_filter_stats`, migration/API/화면
- 범위 제외: 네이버 뉴스 API, P4-001 `/api/settings`, 분류·AI·군집화 리팩터링

## 구현 결과

- 일반 언론기사는 `config/trusted_media.yaml`의 20개 매체 원문 도메인만 허용한다.
- 공식자료와 사고 공식 출처는 언론사 목록과 별도로 허용한다.
- Google RSS의 `<source url>` 누락은 `unknown_publisher`로 제외한다.
- 허용목록 밖 매체는 Sentinel 일치만으로 자동 허용하지 않는다.
- `articles.publisher_id/publisher_allowed`와
  `collection_runs.source_filter_stats_json`을 migration `0009`로 추가했다.
- 수집 응답과 실행 조회 API가 `source_filter_stats`를 반환하고, 수집 화면은
  허용 합계와 제외 건수를 표시한다.

## 공식 도메인 접속 점검

2026-07-16에 HTTPS 연결을 직접 확인했다. 대통령실·국무조정실·기후에너지환경부·
정책브리핑·ALIO·국가법령정보센터·KESCO·소방청·행정안전부·한전·전력거래소는
200 응답을 확인했다. `moef.go.kr`은 `mofe.go.kr`, `motie.go.kr`은
`motir.go.kr`로 최종 이동해 기존·신규 도메인을 모두 예외에 넣었다. 국회 두
도메인은 서버의 400 응답까지 연결됐고, 경찰청은 307 응답 뒤 후속 연결이
시간초과되어 완전한 200 확인은 하지 못했다.

## migration·복구

- 앱 시작 시 migration 대기가 있으면 기존 SQLite 온라인 백업을 먼저 만든 뒤
  `0009_trusted_media.sql`을 적용한다.
- 복구가 필요하면 앱을 종료하고 migration 직전 `backups/db/*.db`를 운영 DB로
  복사한 뒤, 코드도 migration 이전 revision으로 되돌린다. SQLite의 `ALTER TABLE`
  컬럼 삭제를 운영 DB에 직접 시도하지 않는다.

## 검증 결과

### 자동

- `.venv/bin/python -m pytest -q`: 160 passed
- `.venv/bin/ruff check .`: 통과
- `find frontend -name '*.js' -print0 | xargs -0 -n1 node --check`: 통과
- `git diff --check`: 통과
- 경고: FastAPI/Starlette의 기존 deprecation 경고 3건. 실패로 숨기지 않고 유지한다.

### 수동·화면

- 임시 DB와 `?noauto`로 운영 데이터·외부 뉴스 수집을 건드리지 않고 화면을 열었다.
- 최신 실행 API에서 불러온 `원본 12건 · 출처 허용 5건 / 제외 7건` 표시를 확인했다.
- 초기 화면, 샘플 기사 카드, 요약 영역, 날짜·내보내기·인쇄 버튼 렌더링을 확인했다.
- Console 신규 오류 확인, 실제 기사 선택/해제·중요·메모 저장, 날짜 변경, 요약 직접
  수정, JSON·CSV 실제 다운로드·재가져오기, 인쇄 미리보기는 UI 자동 조작 중 사용자
  개입이 감지되어 수행하지 않았다. 해당 상태·왕복·finalize의 서버 경로는 전체 pytest에
  포함됐지만, 이번 화면 수동 검증을 통과한 것으로 대체 표기하지 않는다.
