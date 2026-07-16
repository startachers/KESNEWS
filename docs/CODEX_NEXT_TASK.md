# 기사 수집 설계 변경 — 다음 작업

## 현재 체크포인트

`new_rules_news_clip.md` §18의 **단계 3. 신뢰 언론사 허용목록**은 2026-07-16에
구현·검증을 완료했다. 단계 4(네이버 뉴스 API)와 P4-001 `/api/settings`는 이번
변경에 포함하지 않았다.

## 단계 3 완료 상태

- `config/trusted_media.yaml`에 신뢰 언론사 20개, 공식자료·중대사고 공식 출처,
  담당자 승인 중대사고 언론 설정을 분리했다.
- 일반 언론은 원문 도메인 허용목록을 통과한 경우만 저장하고, 허용목록 밖 지역
  언론은 중대사고라도 자동 허용하지 않는다.
- Google 뉴스 RSS는 `<source url>`을 추출해 판별하며 누락 시 출처 미상으로 제외한다.
- migration `0009`가 기사별 판별 결과와 실행별 `source_filter_stats`를 보존한다.
- 수집 API와 화면에서 공식자료·신뢰 언론·제외·출처 미상 통계를 확인할 수 있다.
- 회귀 기록: `docs/regression/NEWS_COLLECTION_STAGE3_2026-07-16.md`

## 다음 범위

다음 작업을 시작할 때는 별도 지시를 따른다. `new_rules_news_clip.md`가 정한 다음
분할 단계는 **단계 4. 네이버 뉴스 API provider**이며, P4-001은 계속 별도 후속이다.

## 계속 범위 밖

- P4-001 `/api/settings`와 검색 요청 바디 축소
- 분류·AI·이슈 군집화 리팩터링
- `legacy/kesco_media_briefing_original.html` 수정

## 기본 검증 명령

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
find frontend -name '*.js' -print0 | xargs -0 -n1 node --check
git diff --check
```
