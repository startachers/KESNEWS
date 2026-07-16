# 기사 수집 설계 변경 — 다음 작업

## 현재 체크포인트

`new_rules_news_clip.md` §18의 **단계 2. 사고 Sentinel + 파이프라인 순서**는
2026-07-16에 구현·검증을 완료했다. 단계 3(신뢰 언론사 허용목록)과 단계 4
(네이버 뉴스 API)는 이번 변경에 포함하지 않았다.

## 단계 1 완료 상태

- Google News 정본 검색식 17개를 프런트 기본값, 수동·자동수집 설정, 검색 규칙 예시에 반영
- `settingsVersion: 3` 마이그레이션으로 일반 설정을 보존하고 검색식만 교체
- 검색 설정 화면을 5개 그룹·17행으로 구성하고 개별 on/off 유지
- 백엔드 `rules-v3` 7단계 rank와 17개 `primary_category` 판정 적용
- `config/people.yaml` 값을 수집 직전에 `{OR_current_*}` 토큰으로 치환
- `new_rules_news_clip.md` §17 완료 기준 1~4와 공통 18 자동 회귀 검증 완료

## 단계 2 완료 상태

- §6·§7 Sentinel이 수치 미상 중대화재·정전을 보존하고 계획정전 안내를 제외한다.
- 연합뉴스와 공통 수집 파이프라인에서 Sentinel을 관련도보다 먼저 판정한다.
- `collectionLimit` 절단 시 Sentinel·rank 1을 보호하고 기본값을 400으로 맞췄다.
- migration `0008`에는 `article_assessments.incident_json`만 추가했다.
- API·기사 카드·JSON schemaVersion 6·CSV에서 사고 정보를 저장·표시·왕복한다.
- 회귀 기록: `docs/regression/NEWS_COLLECTION_STAGE2_2026-07-16.md`

## 다음 구현 범위: 단계 3만

다음 작업은 `new_rules_news_clip.md` §18의 **단계 3. 신뢰 언론사 허용목록**만
구현한다. `trusted_media.yaml`, 공식자료 예외, Google `<source url>` 판별,
`source_filter_stats`와 완료 기준 10~12, 16이 범위다. 단계 4 네이버 provider는
함께 시작하지 않는다.

## 범위 밖

- P4-001 `/api/settings`와 검색 요청 바디 축소
- 단계 3의 trusted media 허용목록, 공식자료 예외, Google `<source url>` 판별
- 단계 4의 네이버 provider와 자격정보 로딩
- 분류·AI·이슈 군집화의 별도 리팩터링

## 검증 명령과 보고

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
find frontend -name '*.js' -print0 | xargs -0 -n1 node --check
git diff --check
```

단계 3 작업보고에는 변경 파일, §17 완료 기준별 결과, 자동·수동 검증 결과,
미수행 항목, `KNOWN_RISKS.md`에 남은 NC-004와 P4-001을 포함한다.
