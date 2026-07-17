# CEO 브리핑 자동선정 P0 회귀 기록 — 2026-07-17

## 범위

- 중대화재 Sentinel과 공사 관련도 분리
- 화재 원인을 확정 수준과 분야의 두 축으로 저장
- 유효 후보가 충분하면 Gemma 추천을 정확히 12건으로 강제
- 핵심 6건은 공사 관련성, 추가 6건은 정부·경제·AI 일반 중요 동향 허용
- 정부부처·경제·AI 분야를 필수 할당에서 품질 gate 이후 우선 고려로 변경
- 추천 응답의 후보 ID·중복·연속 순위·상한·최소 관련성 검증
- 동일 이슈 대표기사 1건 제한과 제목-핵심주제 정합성 gate
- 모델 응답의 동일 이슈 중복·제목 불일치 서버 강제 거부
- JSON 정식 백업 schemaVersion 10과 CSV 원인 두 축 왕복

## 데이터 변경과 복구

원인 두 축은 기존 `article_assessments.incident_json`에 하위호환 필드로 추가한다. migration
`0015_incident_cause_axes.sql`은 물리 컬럼을 바꾸지 않고 rules-v11 재분류 전에 자동 DB 백업이
생성되는 경계를 만든다. 문제가 생기면 `scripts/restore_database.py`로 해당 사전 백업을 복원할
수 있다. 기존 `cause_status`와 JSON schemaVersion 1~9 읽기는 유지한다.

## 자동 검증

```text
.venv/bin/python -m pytest -q
260 passed, 3 warnings

.venv/bin/ruff check .
All checks passed!

node --check frontend/js/features/auto-selection.js
node --check frontend/js/features/articles.js
성공

git diff --check
성공
```

실데이터 문구 fixture에서 창녕 화재는 관련도 15·심각도 100·레거시 우선도 reference와
`suspected + negligence`, 아산 화재는 `suspected + electrical`, BIFC 화재는
`suspected + battery`, 공동주택 점검은 관련도 100으로 확인했다. 추천 통합 테스트는 최대치보다
요청 수보다 적은 결과는 거부되며 명시적 apply 전 작업본 revision이 바뀌지 않음을 확인한다.
동일 군집의 후속 보도는 대표기사 1건만 남고, 반도체 실적 종합기사 본문의 부수적인 UPS 배터리
단락은 제목-핵심주제 정합성 gate에서 제외됨을 단위 테스트로 확인한다.

## 수동 회귀

- [x] 실행 중 로컬 서버 health 정상
- [x] 정적 화면 응답에 `Gemma 추천 12건` 표시 확인
- [ ] 브라우저 자동화 도구 미제공으로 실제 추천 모달·원인 배지 시각 확인 미실행
- [ ] 기사 선택·해제, 중요 표시, 메모 저장, 날짜 변경 미실행
- [ ] JSON·CSV 내보내기 UI, 인쇄 미리보기, Console 신규 오류 확인 미실행

미실행 항목의 API·JSON/CSV 왕복과 JavaScript 구문은 자동 테스트로 확인했다. 현재 실행 중인
서버 프로세스는 코드 변경 전에 시작됐으므로 backend v5 적용에는 운영 재시작이 필요하다.

## 의도적으로 제외한 후속 범위

- 군집 검토별점의 절대 편집등급 재설계
- 사건 군집 anchor 강화와 오군집 교정
- 날짜별 `briefing_topics` 계층 및 주제 단위 proposal/apply
- Top Issues 화면의 주제 단위 전환

위 항목은 기존 자동선정 오류 차단과 섞지 않고 별도 작업으로 진행한다.
