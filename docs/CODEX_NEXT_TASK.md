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

## 다음 범위: 단계 4. 네이버 뉴스 API provider (2026-07-16 설계 확정)

`new_rules_news_clip.md` §12·§16.2·§17 완료 기준 13~15를 따른다. NC-004 해소 대상이다.
인증키는 발급 완료되어 프로젝트 루트 `.env`에 `NAVER_CLIENT_ID`/`NAVER_CLIENT_SECRET`로
저장돼 있다.

### 0. 선행 필수: .env 로딩 추가

현재 코드베이스는 `.env`를 읽는 곳이 전혀 없다(전부 `os.environ` 직접 조회).
python-dotenv 같은 신규 의존성을 추가하지 말고, `KEY=value` 줄만 파싱하는 작은
로더(`backend/app/core/env.py` 등, 주석·빈 줄 무시, 기존 환경변수 우선)를 만들어
`scripts/run_server.py`와 `scripts/run_automated_collection.py` 시작 시 호출한다.
launchd plist에 키를 굽지 않는다(키 교체 시 재설치가 필요해지므로). 기존
`POLICY_BRIEFING_SERVICE_KEY`도 같은 로더로 읽히게 된다.

### 1. 신규 adapter: backend/app/services/collection/naver_news.py

- `GET https://openapi.naver.com/v1/search/news.json?query={단순검색어}&display=100&start=1&sort=date`
  헤더 `X-Naver-Client-Id`/`X-Naver-Client-Secret`. 기존 `http.http_get` 사용, timeout 15초.
- 네이버는 기간 필터가 없으므로 `pubDate`가 lookback 경계를 벗어날 때까지 `start`를
  100씩 증가시키며 최대 3페이지까지만 조회한다.
- 정규화(§12.3): `title`/`description`의 `<b>` 등 HTML 태그·엔티티 제거,
  `pubDate` RFC 1123 → ISO 8601(기존 `parse_date`가 이미 처리),
  `url = originallink or link`, **`originalLink` 필드에 originallink를 그대로 보존**
  (media.py:100이 이미 이 camelCase 필드로 언론사를 판별한다), `provider = "네이버 뉴스 API"`.
- 네이버 항목에는 안정적 게시물 ID가 없으므로 `sourceId`는 넣지 않는다
  (source_id 매칭은 정부부처 어댑터 전용, canonical URL·fuzzy 매칭이 담당).

### 2. naverQueries 정의 (§12.2 — 기존 검색식을 그대로 보내면 안 된다)

> 구현 시점 코드에는 후속 산업·거시 검색군 4개가 추가되어 총 21개와
> `settingsVersion: 4`가 존재한다. 이를 되돌리지 않고 21개 모두에 적용하며 버전은 5로 올린다.

- 네이버 query는 불리언 미지원. 검색군마다 공백 AND만 쓰는 단순 검색어
  `naverQueries: string[]`(군당 최대 3개)를 별도 정의한다.
- 반영 위치 세 곳: `frontend/js/state/store.js`의 `DEFAULT_SETTINGS.queries`
  (settingsVersion 올려 기존 localStorage에 병합되게), `config/automated_collection.json`,
  같은 파일 `.example`. 현재 21개 군 전부에 정의한다. 검색어는 회당 최대 63개이고
  검색어별 3페이지를 모두 읽는 최악의 경우 HTTP 요청은 회당 189회·2시간 주기 일 2,268회로,
  일일 한도 25,000 대비 여유가 있다.
- 프런트는 `runSearch` 요청 바디의 각 query 객체에 `naverQueries`를 실어 보낸다.

### 3. collector.py 배선·우선순위(§12.4)

- 검색군별로 인증키가 있으면 네이버를 먼저 호출하고, 기존 Google RSS 경로도 그대로
  유지한다(동일 기사는 기존 dedup이 observation 2건으로 병합 — §16.2 표 참조).
- 네이버 실패(401·429·시간초과)는 전체 수집 실패로 만들지 않는다. 해당 군은 RSS 결과로
  계속 진행하고 `warnings`에 남긴다. 오류 메시지·로그·내보내기에 키·헤더를 절대 포함하지
  않는지 테스트로 확인한다(§17 완료 기준 15).
- 키 미설정이면 네이버 호출 자체를 건너뛴다(현 동작 유지).
- 응답에 네이버 상태를 실어 화면은 `네이버 뉴스 API 연결됨 / 미설정 / 오류` 3가지만
  표시한다.

### 4. 언론사 판별(§14 연동)

- `originallink` 도메인으로 허용목록 판별(이미 media.py에 구현됨).
- `originallink`가 없고 `link`가 `n.news.naver.com`이면 `unknown_publisher`로 제외
  — `_publisher_url`이 빈 문자열을 돌려주므로 현 로직으로 자동 충족되는지 테스트로 못박는다.

### 5. 테스트(§16.2 표를 그대로 케이스로)

- 단위: 정규화(HTML 태그 제거·날짜 변환), originallink 유무별 판별, 페이지네이션이
  lookback 경계·3페이지에서 멈추는지, 인증 실패가 warning으로만 남는지.
- 통합: 네이버+Google 동일 기사 → 기사 1건·observation 2건·query_group 병합.
- 회귀: 기존 전체 pytest·ruff·node --check·git diff --check.

### 6. 문서

- `docs/KNOWN_RISKS.md` NC-004를 해소로 갱신, `.env` 로딩 방식 기록.
- `docs/OPERATIONS_RUNBOOK.md`에 키 설정 위치(.env)와 상태 표시 3종 추가.

P4-001(`/api/settings`)은 계속 별도 후속이다.

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
