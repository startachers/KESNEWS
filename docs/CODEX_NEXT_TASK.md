# 기사 수집 설계 변경 — 다음 작업

## 현재 체크포인트

`new_rules_news_clip.md` §18의 **단계 3. 신뢰 언론사 허용목록**은 2026-07-16에
구현·검증을 완료했다. 단계 4(네이버 뉴스 API)와 P4-001 `/api/settings`는 이번
변경에 포함하지 않았다.

## 단계 3 완료 상태

- `config/trusted_media.yaml`에 신뢰 언론사 50개, 공식자료·중대사고 공식 출처,
  담당자 승인 중대사고 언론 설정을 분리했다.
- 초기 20개에 주요 경제·지역 매체 15개와 전기·에너지·소방안전 전문 매체 15개를
  추가했다. 포털·해외 재배포처·연예/스포츠·출처 불명확 군소 매체는 제외한다.
- 일반 언론은 원문 도메인 허용목록을 통과한 경우만 저장하고, 허용목록 밖 지역
  언론은 중대사고라도 자동 허용하지 않는다.
- Google 뉴스 RSS는 `<source url>`을 추출해 판별하며 누락 시 출처 미상으로 제외한다.
- migration `0009`가 기사별 판별 결과와 실행별 `source_filter_stats`를 보존한다.
- 수집 API와 화면에서 공식자료·신뢰 언론·제외·출처 미상 통계를 확인할 수 있다.
- 단계 3 이전 미판별 자동 기사는 후보에서 제외하고, 담당자 선택·메모 등이 있는
  기존 기사는 계속 보존한다.
- 회귀 기록: `docs/regression/NEWS_COLLECTION_STAGE3_2026-07-16.md`

## 별도 추가 작업: 정부부처 직접 수집 (2026-07-16)

`new_rules_news_clip.md` 분할 단계와는 별도로, 검색식(Google RSS)만으로는 놓치는 정부부처
원문을 보완하기 위해 기관 직접 수집을 추가했다. 아래 단계 4(네이버 API)보다 먼저 구현했으며
단계 4 순서를 대체하지 않는다.

- `find_matching_article`이 canonical URL보다 `(provider, source_id)` 완전일치를 먼저
  확인한다. `articles.article_observations`의 `provider_item_key` 색인을 migration
  `0010`으로 추가했다.
- `opm_press.py`(국무조정실 보도자료, `articleNo` 기준)와 `me_press.py`(기후에너지환경부
  보도자료, `boardId` 기준)가 실제 목록 페이지 HTML을 정규식으로 파싱한다.
  `automated_collection.json`의 `enableOpmPress`/`enableMePress`와 프런트 설정
  화면의 동명 체크박스(기본 켬)로 켠다. `queries`/`coreKeywords` 등과 같은 요청 바디
  경로이므로 프런트에서 수동으로 "기사검색"을 눌러도 함께 호출된다.
- `policy_briefing.py`(정책브리핑 보도자료 OpenAPI, data.go.kr 서비스ID 1371000)는
  엔드포인트만 확인했고 서비스키 발급 전이라 응답 필드명이 미확인 상태다. 방어적으로 여러
  후보 필드명을 시도한다. 서비스키는 NC-004(네이버 자격정보)와 같은 원칙으로 요청
  바디·프런트에 두지 않고 서버 환경변수 `POLICY_BRIEFING_SERVICE_KEY`로만 읽으며, 비어
  있으면 이 provider 자체를 수집에 추가하지 않는다. 실제 키를 발급받으면
  `backend/app/services/collection/policy_briefing.py`의
  `_TITLE_KEYS`/`_BODY_KEYS`/`_DEPT_KEYS`/`_DATE_KEYS`/`_URL_KEYS`/`_ID_KEYS` 후보를
  실제 응답과 대조해 확정해야 한다.
- 대통령실(`president.go.kr`)은 WAF가 브라우저가 아닌 요청을 전부 에러 페이지로
  돌려보내 직접 크롤링을 확인하지 못했다. 헤드리스 브라우저 없이는 어렵다고 보고, 당분간
  정책브리핑 API·Google RSS·기존 `official_source_exemptions`에 의존한다.
- 공식 도메인 검증을 통과한 위 정부부처 직접 수집 자료는 일반 관련도 탈락 규칙에서
  제외하고 최소 `review`로 보존한다. 보고일 기간 범위와 전체 제외 규칙은 유지한다.
- 검증: `.venv/bin/python -m pytest -q`(172 passed), `.venv/bin/ruff check .`,
  `tests/unit/test_gov_adapters.py`(실제 페이지 HTML 구조로 만든 fixture 기반).

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
