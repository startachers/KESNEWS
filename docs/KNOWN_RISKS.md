# 현행 HTML 위험 등록부

이 문서는 기존 단일 HTML의 알려진 위험을 기록한다. Phase 1은 파일 분리만 수행하므로 아래 로직을 임의로 수정하지 않는다. 각 항목은 지정 Phase에서 테스트와 함께 처리한다.

| ID | 현행 위험 | 영향 | 회귀 기준 | 수정 Phase |
|---|---|---|---|---|
| LEG-001 | 일부 provider만 성공하면 기존 자동 수집 기사가 새 성공 결과로 교체돼 빠질 수 있음 | 부분 장애 시 후보 기사 소실 | 부분 성공 시 현재 동작을 기록하고 데이터 손실 가능성을 문서화 | Phase 3 |
| LEG-002 | AI 응답의 `articleIds`가 실제 입력 ID인지 검증하지 않음 | 존재하지 않는 근거가 보고문에 표시될 수 있음 | 잘못된 A99 응답 fixture를 준비 | Phase 7 |
| LEG-003 | `decisionPoints`, `riskOutlook`, management message 등에 근거 ID 구조가 없음 | 분석·전망의 근거 추적 불완전 | 현행 출력 구조 보존 | Phase 7 |
| LEG-004 | JSON import가 action note, 일부 상태·설정·오류 이력 등을 완전 복원하지 않음 | 백업이라고 믿고 복구하면 내용 누락 | 현행 export→import 차이를 기록 | Phase 4 |
| LEG-005 | CSV export/import가 category·risk 등의 한글 label과 내부 enum을 완전 왕복하지 못함 | 재가져오기 시 분류 왜곡 | export→import 결과 비교 | Phase 4 |
| LEG-006 | CSV 셀의 spreadsheet formula 시작문자 escape가 없음 | Excel·Numbers에서 의도치 않은 수식 실행 가능 | `=1+1`, `@SUM(...)` fixture | Phase 4 |
| LEG-007 | 기사 선택 해제와 휴지통 삭제의 장기 보존 의미가 명확하지 않음 | 메모·중요 표시 손실 가능 | 현행 UI 동작 캡처 | Phase 4 |
| LEG-008 | 제목 키워드 점수로 예방·사고, 감사·감사패가 충돌할 수 있음 | 위험도·긍부정 오분류 | 필수 한국어 fixture | Phase 5 |
| LEG-009 | 유사 제목 병합 시 provider별 관측·실행 이력이 단일 article 객체에 축약됨 | 수집 경로 감사·장애 추적 불가 | duplicateSources 현행 값 기록 | Phase 3~4 |
| LEG-010 | 재군집화 모델이 아직 없어 향후 수동 이슈 편집 보호 계약이 필요함 | 자동 재분석이 담당자 편집을 덮을 위험 | API·DB 계약 선확정 | Phase 6 |
| LEG-011 | Google 뉴스 RSS의 기사 URL은 인코딩된 중계 주소여서 리다이렉트 추적 없이 원문 URL을 얻기 어려움 | canonical URL 기반 완전 중복 제거가 실패해 동일 기사가 중복 표시될 수 있음 | 중계 URL 기사 fixture로 현행 dedup 결과 기록. 원문 해석 실패 시 중계 URL을 canonical로 유지하고 제목 기반 dedup에 의존함을 명시 | Phase 3 |
| LEG-012 | 연합뉴스 전체 뉴스 RSS(`news.xml`)는 최신 120건만 제공해 실측 기준 약 4~5시간분만 담김. lookback 48시간을 채우지 못함 | 하루 1회 수집 시 연합뉴스 직접 피드의 대부분을 놓치고 Google 뉴스 검색 경로에 의존 | 수집 시점 피드의 실제 시간 범위를 collection run에 기록 | Phase 3에서 섹션별 피드 추가 또는 `launchd` 주기 수집으로 보완, Phase 9에서 주기 확정 |

## Phase 1 처리 원칙

- 위 항목을 코드에서 고치지 않는다.
- 원본과 분리본이 동일하게 동작하는지 확인한다.
- 차이를 발견하면 회귀 버그로 기록하고 Phase 1 안에서 원본 동작에 맞춘다.
- 명백한 데이터 손상 가능성도 Phase 1에서는 별도 승인 없이 로직 변경하지 않는다.
