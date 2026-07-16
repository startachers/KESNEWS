# API·데이터 계약

- 문서 상태: 구현 전 필수 계약
- 적용 시작: 백엔드·SQLite 구현 전
- 우선순위: 이 문서와 일반 아키텍처 설명이 충돌하면 이 문서를 따른다.
- 기준 시간대: 보고일은 `Asia/Seoul`, 저장 시각은 UTC ISO 8601

---

## 1. 브리핑 작업본과 최종 버전

### 1.1 핵심 결정

보고일마다 **편집 가능한 작업본은 정확히 1개**만 둔다. 최종 확정본은 별도 불변 snapshot으로 누적한다.

```text
briefings            보고일별 현재 작업본, report_date UNIQUE
briefing_versions    최종 확정 snapshot, (briefing_id, version) UNIQUE
```

`briefings.revision`은 화면의 오래된 저장 요청을 막기 위한 편집 revision이다. `briefing_versions.version`은 CEO에게 보고한 최종본 번호다. 두 값을 혼용하지 않는다.

### 1.2 작업본 상태

```text
draft      작성 중
reviewed   검토 완료
final      현재 작업본이 최신 최종본과 동일하며 잠긴 상태
```

- `finalize`는 작업본을 삭제하거나 새 작업본으로 바꾸지 않는다.
- `finalize` 시 `briefing_versions`에 불변 snapshot을 추가하고 작업본을 잠근다.
- `reopen`은 기존 최종 snapshot을 보존한 채 작업본을 다시 `draft`로 전환한다.
- 재확정하면 `version`을 1 증가시킨 새 snapshot을 만든다.

### 1.3 날짜만 받는 조회 규칙

| 요청 | 선택 규칙 |
|---|---|
| `GET /api/briefings?limit=N` | 저장된 작업본을 보고일 내림차순으로 조회. 기본 100건, 최대 365건 |
| `GET /api/briefings/{date}` | 해당 날짜의 유일한 현재 작업본 |
| `GET /api/briefings/{date}/versions` | 최종 snapshot 목록 |
| `GET /api/briefings/{date}/versions/{version}` | 지정 최종 snapshot |
| `GET /preview/{date}` | 현재 작업본의 읽기 전용 미리보기 |
| `GET /report/{date}` | 가장 높은 최종 version. 최종본이 없으면 404 |
| `GET /report/{date}?version=N` | 지정 최종 version |

`GET`은 작업본을 자동 생성하지 않는다. 작업본 생성은 다음 요청으로만 수행한다.

```text
PUT /api/briefings/{date}
```

해당 날짜가 없으면 생성하고, 있으면 전달된 필드만 갱신한다.

### 1.4 mutation 동시성

모든 작업본 mutation은 `expectedRevision`을 받는다.

```json
{
  "expectedRevision": 12,
  "patch": {
    "preparedBy": "홍보실"
  }
}
```

- 최초 생성은 `expectedRevision: 0`을 사용하고 생성 후 revision은 1이다.
- 기존 작업본은 현재 DB revision과 일치하면 저장 후 revision을 1 증가시킨다.
- 불일치하면 `409 BRIEFING_REVISION_CONFLICT`를 반환한다.
- 최종 상태에서 일반 mutation을 요청하면 `409 BRIEFING_FINALIZED`를 반환한다.

단일 사용자 환경이지만 브라우저 탭 중복과 오래된 화면 저장을 막기 위해 이 계약을 유지한다.

---

## 2. 기사 선택·중요 표시·메모 보존

### 2.1 표준 동작

기사 선택 해제는 row 삭제가 아니다.

```text
PATCH /api/briefings/{date}/articles/{article_id}
```

요청 예시:

```json
{
  "expectedRevision": 12,
  "selected": false
}
```

`selected`만 바꾸고 다음 값은 그대로 보존한다.

- `starred`
- `note`
- `sort_order`
- `dismissed`
- 수동 분류 override

### 2.2 브리핑 기사 상태

`briefing_articles`는 다음 필드를 가진다.

```text
briefing_id
article_id
selected
starred
top_issue
note
dismissed
sort_order
created_at
updated_at
```

유효 상태:

| 상태 | selected | dismissed | 의미 |
|---|---:|---:|---|
| 일반 후보 | false | false | 목록에 보이지만 미선정 |
| 브리핑 선정 | true | false | 요약·보고 대상 |
| 숨김 | false | true | 해당 날짜 작업목록에서 숨김, 복원 가능 |

`top_issue`는 개별 기사를 Top Issues에 직접 올리는 수동 태그다. `selected`(브리핑 선정),
`starred`(중요 기사)와 서로 독립이다. `dismissed=true`가 되면 서버가 `selected=false`로 정규화한다.

### 2.3 DELETE 사용 제한

다음 route는 두지 않는다.

```text
DELETE /api/briefings/{date}/articles/{article_id}
```

UI의 휴지통은 `dismissed=true` patch로 처리한다.

원본 기사 물리 삭제는 다음 조건을 모두 만족하는 수동 추가 기사에만 허용한다.

```text
DELETE /api/articles/{article_id}
```

- `manual=true`
- 어떤 최종 snapshot에도 포함되지 않음
- 다른 보고일의 메모·선정 이력이 없음
- 사용자 확인값 `confirm=true`

조건을 만족하지 않으면 `409 ARTICLE_IN_USE`다.

### 2.4 briefing_articles row 생성 시점

수집 실행은 `briefing_articles` row를 만들지 않는다. 수집은 `articles`와 `article_observations`만 갱신한다.

- row는 해당 기사에 대한 **첫 PATCH 시 upsert로 생성**한다. 생성 기본값은 `selected=false`, `starred=false`, `top_issue=false`, `dismissed=false`, `note` 없음, `sort_order`는 목록 끝이다.
- 해당 날짜의 작업본이 없으면 `404 BRIEFING_NOT_FOUND`다. 작업본은 1.3의 `PUT /api/briefings/{date}`로만 생성한다.
- row가 없는 기사는 “일반 후보(미선정)”와 의미가 같다. finalize는 그 시점의 유효 상태를 snapshot에 복사하므로 row 유무가 결과에 영향을 주지 않는다.

### 2.5 후보 목록 조회 규칙

`GET /api/articles?report_date=YYYY-MM-DD`는 다음 합집합을 반환한다.

1. 해당 `report_date`에 귀속된 collection run의 observation이 연결되고
   `publisher_allowed=true`인 기사
2. 해당 날짜의 `briefing_articles` row가 있는 기사
3. 해당 날짜에 수동 추가된 기사

- 각 기사에는 해당 날짜의 편집 상태(`selected`, `starred`, `topIssue`, `note`, `dismissed`)를 join해 반환한다. row가 없으면 기본 상태를 반환한다.
- `firstObservedAt`은 기사가 로컬 수집기에 최초로 들어온 UTC 시각이다. 화면의
  `관련기사 수집순`은 적용된 이슈의 관련기사 수(대표 기사 제외)를 내림차순으로 사용한다.
  같은 건수이면 `firstObservedAt` 오름차순, 다시 같으면 공사 관련도순으로 정렬한다.
- 군집을 카드 1건으로 접어 표시할 때는 현재 정렬에서 가장 앞선 구성 기사를 대표 카드로
  사용하고, 군집 카드와 단일 기사를 같은 정렬 위치에 배치한다. 대표 기사를 무작위로 바꾸지 않는다.
- 단계 3 이전 자동수집 기사처럼 `publisher_allowed`가 미판별(`null`)인 기사는 일반
  후보에서 제외한다. 단, 2번 합집합에 해당하는 기존 담당자 선택·중요·메모·숨김 상태는
  출처 판별값과 무관하게 계속 보존·표시한다.
- `include_dismissed=false`면 `dismissed=true` 기사를 제외한다.
- `GET /api/issues?report_date=`는 위 후보 기사가 유효 구성에 1건 이상 포함된 이슈를 반환하며 `briefing_issues`의 수동 상태를 합쳐 반환한다.

Top Issues는 담당자가 직접 태그한 항목만 표시한다. 군집 태그는 `briefing_issues.selected`,
개별 기사 태그는 `briefing_articles.top_issue`에 저장하며 두 종류를 합쳐 최대 3개로 제한한다.
재군집화는 기사 단위 `top_issue`를 변경하지 않는다.

### 2.6 정렬 변경

단건 순서 변경은 2.1의 PATCH로 `sort_order`를 갱신한다. 전체 재정렬은 bulk mutation 하나로 처리한다.

```text
PUT /api/briefings/{date}/article-order
```

```json
{
  "expectedRevision": 12,
  "articleIds": ["id-3", "id-1", "id-2"]
}
```

나열된 기사에 순서대로 `sort_order`를 다시 부여하고, 나열되지 않은 기사의 값은 유지한다.

---

## 3. 수집 provider·실행 이력·중복 병합

### 3.1 매체와 provider를 구분한다

- `article.source`: 기사를 발행한 언론사
- `provider`: 기사를 발견한 수집 경로(연합뉴스 RSS, Google 뉴스 RSS, GDELT 등)

하나의 기사가 여러 provider에서 발견될 수 있으므로 `articles.provider` 단일 필드에 저장하지 않는다.

### 3.2 필수 테이블

```text
collection_runs
collection_run_providers
article_observations
articles
```

#### collection_runs

전체 수집 실행의 요약이다.

```text
id
report_date
started_at
finished_at
status              success | partial | failed
lookback_hours
raw_count
accepted_count
unique_count
stale_reused_count
warning_count
error_count
source_filter_stats_json
```

#### collection_run_providers

provider 또는 provider+검색그룹 단위 결과다.

```text
id
collection_run_id
provider
query_group_id
status              success | failed | skipped
started_at
finished_at
raw_count
accepted_count
duplicate_count
stale_reused_count
warning_message
error_code
error_message
```

#### article_observations

수집원이 반환한 개별 원본 관측이다. 완전 중복으로 합쳐져도 삭제하지 않는다.

```text
id
article_id
collection_run_provider_id
provider
provider_item_key
query_group_id
raw_url
raw_title
raw_source
raw_published_at
raw_description
raw_payload_json
observed_at
dedup_method         canonical_url | content_key | exact_title | fuzzy_same_copy | new
dedup_score
```

### 3.3 중복 병합 규칙

1. 각 provider 응답을 먼저 `article_observations`로 기록한다.
2. 정규화 후 기존 `articles`와 동일 원문인지 판정한다.
3. 동일 원문이면 하나의 `article_id`에 여러 observation을 연결한다.
4. `articles`에는 대표 정규화 값만 두고 provider 이력은 observation에서 조회한다.
5. 같은 사건을 다른 매체가 별도로 쓴 기사는 병합하지 않고 이슈 군집화에서 묶는다.

### 3.4 부분 수집 실패 시 보존 규칙

provider 일부만 성공한 실행의 status는 `partial`이다.

- 성공 provider의 새 observation은 upsert한다.
- 실패 provider에서 직전 정상 실행에 수집된 기사 후보를 삭제하지 않는다.
- 검색 기간 안에 있는 기존 기사는 `stale=true`, `staleReason=provider_failed`로 반환할 수 있다.
- 화면에는 마지막 정상 observation 시각과 실패 provider를 함께 표시한다.
- 전체 후보 목록을 “이번 실행에서 성공한 provider 결과만”으로 교체하지 않는다.

### 3.5 수집 실행 요청과 보고일 귀속

```text
POST /api/collections
```

```json
{
  "report_date": "2026-07-15",
  "lookback_hours": 24
}
```

- `report_date` 생략 시 `Asia/Seoul` 기준 오늘 날짜를 사용한다.
- `collection_runs.report_date`는 실행 시각이 아니라 **요청의 `report_date`**에 귀속한다. 자정 전후 실행이 어제·오늘 어느 보고일에 속하는지 서버가 추측하지 않는다.
- 일일 브리핑의 자동수집 범위는 수집 실행 시각 기준 최근 24시간으로 고정한다. 구버전
  클라이언트가 더 큰 `lookback_hours`를 보내더라도 서버는 24시간으로 제한한다.
- 같은 보고일의 이전 실행에서 관측됐지만 최신 24시간 범위를 벗어난 일반 자동 후보는
  목록에서 제외한다. 기사 원본과 observation은 삭제하지 않으며, 담당자가 선택·메모·중요·
  숨김 처리한 기사와 수동 등록 기사는 보존한다.

### 3.6 신뢰 출처 필터와 통계

- 일반 언론기사는 `config/trusted_media.yaml`의 원문 도메인 허용목록을 통과해야 저장한다.
- 정부·국회·공공기관 공식 도메인은 일반 언론사 허용목록과 별도로 허용한다.
- 국무조정실·기후에너지환경부 직접 수집과 정책브리핑 API 자료는 공식 도메인 검증을 통과하면 일반 관련도 탈락 규칙을 적용하지 않는다. 단, 보고일 기간 범위와 전체 제외 규칙은 그대로 적용한다.
- Google 뉴스 RSS는 중계 기사 URL이 아니라 `<source url>` 도메인으로 판별하며, 값이 없으면 `unknown_publisher`로 제외한다.
- 판별 결과는 `articles.publisher_id`, `articles.publisher_allowed`에 저장한다. 수동 추가 기사는 출처 필터 대상이 아니므로 두 값이 `null`일 수 있다.
- 실행별 `source_filter_stats_json`은 `raw_results`, `official_sources`, `trusted_media`, `rejected_untrusted_media`, `unknown_publisher`를 보존한다. `unknown_publisher`는 제외 건수의 부분집합이다.
- `POST /api/collections`, 최신 실행 조회, 실행 ID 조회는 같은 통계를 `source_filter_stats`로 반환한다.

---

## 4. 판정 점수·임계값·규칙 충돌

### 4.1 판정 축

다음 값은 독립적으로 계산한다.

```text
relevance_score   0~100, 공사·전기안전 업무와의 직접성
severity_score    0~100, 사고·감사·수사·피해의 심각성
spread_score      0~100, 매체 수·주요 매체·확산 속도(이슈 단계)
event_type        accident | prevention | management_risk | policy | achievement | community | general | mixed
priority          required | review | reference
```

관련도 점수만으로 `required`를 만들지 않는다.

hard floor·cap 규칙이 사용하는 relevance **등급**은 점수에서 다음처럼 유도한다.

```text
direct    organization_terms 중 하나가 제목·본문에 매칭된 기사 (direct_mention)
related   direct가 아니고 relevance_score ≥ 40
low       direct가 아니고 relevance_score < 40
```

- `direct`는 점수가 아니라 기관명 매칭 여부로 판정한다. 점수가 낮아도 직접 거론이면 `direct`다.
- `related` 경계값 40은 `config/classification_rules.yaml`의 `relevance_tiers.related_min_score`로 조정한다.
- 등급 판정 결과와 근거 매칭 문자열을 `auto_reasons_json`에 기록한다.

### 4.2 자동 우선도 점수

기사 단계:

```text
article_priority_score = 0.55 × relevance_score + 0.45 × severity_score
```

이슈 단계:

```text
issue_priority_score = 0.40 × relevance_score
                     + 0.40 × severity_score
                     + 0.20 × spread_score
```

기본 임계값:

```text
required   75 이상
review     45 이상 75 미만
reference  45 미만
```

### 4.3 hard floor와 cap

점수 계산 후 다음 순서로 결정한다.

1. 점수 임계값으로 기본 priority를 정한다.
2. event type cap을 적용한다.
3. hard floor를 적용한다. 명시된 예외 hard floor는 일반 cap보다 우선한다.
4. 담당자 `final_priority`가 있으면 마지막에 덮어쓴다.

- 공사 직접 거론 + 사망·중상·중대화재·대규모 정전·수사·압수수색: 최소 `required`
- 공사 직접 거론 + 감사원 감사·국정감사·고발·중대한 법 위반: 최소 `review`; 심각도 70 이상이면 `required`
- 전기안전 관련 사망·다수 인명피해가 있으나 공사 직접 거론이 없음: 최소 `review`
- 공식 도메인 검증을 통과한 정부부처 직접 수집 자료: 최소 `review` (관련도만으로 `required` 금지)
- `prevention`, `achievement`, `community`만 있는 기사는 자동 `required` 금지, 최대 `review`
- `low relevance`는 자동 최대 `reference`; 단, 전기안전 분야 중대사고 hard floor가 있으면 `review`
- 담당자 `final_priority`는 모든 자동 floor·cap보다 우선한다.

### 4.4 문맥 판정 순서

규칙 충돌은 다음 순서로 처리한다.

1. **전체 제외 규칙**: 채용공고, 명백한 동명이인 등
2. **구체적 위해·발생 문맥**: `발생`, `사망`, `부상`, `피해`, `대피`, `중단`, `수사`, `압수수색`, `적발`
3. **구체적 경영 리스크 문맥**: `감사원 감사`, `국정감사`, `감사 결과`, `수사 결과`
4. **예방·점검 문맥**: `예방`, `점검`, `교육`, `캠페인`, `훈련`
5. **성과·협력 문맥**
6. **일반 키워드 fallback**

`false_positive_phrases`는 기사 전체를 무조건 무효화하지 않고, 해당 문구 안의 모호한 토큰만 억제한다.

예:

```text
“감사패 전달”           → 일반 ‘감사’ 위험 토큰 억제
“감사패 전달 뒤 감사원 감사 착수” → ‘감사원 감사’는 그대로 경영 리스크
```

사고와 예방 표현이 함께 있으면 문장 단위로 판정한다.

- 실제 발생 문장이 있으면 `accident` 또는 `mixed`
- 예방 문구가 실제 발생 신호를 상쇄하지 않는다.
- 실제 발생 신호가 없고 예방 문맥만 있으면 `prevention`

대통령·국무총리·기후에너지환경부 장관 메시지는 기사 전체의 단순 키워드 동시 출현으로
분류하지 않는다. 같은 문장에서 메시지 주체, 전기·에너지 주제, 지시·주문·당부·강조·
발표·점검 등 발언 또는 행위 단서가 모두 확인돼야 한다. 외국·전직 대통령과 전직 총리는
해당 메시지 분류에서 제외한다. 메시지 주체와 전기·에너지 키워드는 있지만 이 요건을
충족하지 못한 모호한 기사는 AI·전략·재생에너지 등 다른 자동 분류로 넘기지 않고 `other`
(기타)로 격리한다.

모든 자동 판정은 `rule_id`, 점수 breakdown, 적용 floor·cap을 `auto_reasons_json`에 기록한다.

### 4.5 담당자 판정 수정의 동시성

`PATCH /api/articles/{article_id}/assessment`는 브리핑 작업본과 독립적이므로 `expectedRevision`을 요구하지 않는다. 단일 사용자 도구 기준으로 last-write-wins로 처리한다.

- PATCH는 `final_*` 필드만 갱신하고 `auto_*` 필드는 변경하지 않는다.
- `final_*` 값이 하나라도 설정되면 `manual_override=true`로 표시한다.
- 모든 `final_*` 값을 비우면 `manual_override=false`로 되돌리고 화면은 다시 `auto_*`를 사용한다.
- 이후 재분류 실행은 `manual_override=true`인 기사의 `final_*`를 덮어쓰지 않는다.

---

## 5. AI 근거 ID 계약

### 5.0 실행·취소 계약

- `POST /api/briefings/{date}/analyze`는 앱 전체에서 동시에 1건만 실행한다.
- 실행 중 새 분석 요청은 `AI_ALREADY_RUNNING`으로 거부한다.
- `POST /api/briefings/{date}/analysis/cancel`은 해당 보고일의 실행을 실제 Ollama 연결까지 중단한다.
- 브라우저 연결이 끊기거나 총 실행시간 5분을 넘으면 분석을 중단한다.
- 취소·시간초과·앱 재시작은 `ai_runs`를 `failed`로 끝내며 마지막 정상 결과와 담당자 수정본을 보존한다.
- `gemma4:31b`는 기본 16K context와 2,048 출력 token 상한을 사용한다. 환경변수 `KESCO_OLLAMA_NUM_CTX_31B`로 4K 이상 범위에서 조정할 수 있다.
- 성공·실패·취소 뒤 해당 모델을 Ollama 메모리에서 내린다.

### 5.1 근거 index

AI 실행마다 고정 index를 만든다.

```json
{
  "A01": "article-uuid-1",
  "A02": "article-uuid-2"
}
```

이 매핑은 `ai_runs.evidence_json`에 저장한다. 같은 실행 중에는 ID를 재사용하거나 재정렬하지 않는다.

### 5.2 모든 주장 필드의 schema

```json
{
  "managementMessage": {
    "text": "",
    "articleIds": ["A01"]
  },
  "situationSummary": {
    "text": "",
    "articleIds": ["A01", "A02"]
  },
  "keyIssues": [
    {
      "title": "",
      "urgency": "required",
      "summary": "",
      "managementImpact": "",
      "articleIds": ["A01"]
    }
  ],
  "decisionPoints": [
    {
      "text": "",
      "articleIds": ["A01"]
    }
  ],
  "actionItems": [
    {
      "priority": "required",
      "action": "",
      "articleIds": ["A01"]
    }
  ],
  "riskOutlook": {
    "text": "",
    "articleIds": ["A01"],
    "isInference": true
  },
  "limitations": [
    {
      "text": "본문 미확보 기사 2건",
      "articleIds": []
    }
  ],
  "confidence": "medium"
}
```

### 5.3 검증 규칙

- 내용이 있는 `managementMessage`, `situationSummary`, `keyIssues`, `decisionPoints`, `actionItems`, `riskOutlook`는 `articleIds`가 1개 이상이어야 한다.
- 모든 ID는 해당 AI 실행의 evidence index에 존재해야 한다.
- `riskOutlook`은 `isInference=true`를 필수로 한다.
- `limitations`만 빈 근거 배열을 허용한다.
- 잘못된 ID, 빈 근거, schema 오류가 있으면 결과 전체를 적용하지 않는다.
- 서버는 형식교정 재시도를 최대 1회 수행한다.
- 재시도 후에도 실패하면 기존 AI 결과와 담당자 수정본을 유지하고 오류만 기록한다.

---

## 6. 재군집화와 담당자 수정 보존

### 6.1 자동값과 편집값 분리

`issues`는 다음 쌍을 가진다.

```text
auto_title       editor_title
auto_status      editor_status
auto_priority    editor_priority
```

화면 유효값은 `editor_*`가 있으면 editor 값을 사용한다.

### 6.2 구성 기사 override

자동 군집 구성과 담당자 변경을 별도 저장한다.

```text
issue_auto_articles
issue_membership_overrides
```

`issue_membership_overrides.action`:

```text
add       자동 군집과 무관하게 포함
remove    자동 군집에 있어도 제외
```

유효 구성은 다음과 같다.

```text
(auto membership OR manual add) AND NOT manual remove
```

### 6.3 cluster run

재군집화는 즉시 덮어쓰지 않는다.

담당자는 기사별 `군집 선택`을 2건 이상 지정해 다음 API로 수동 군집을 만들 수 있다.

```text
POST /api/issues/manual-group
```

요청은 `reportDate`, `articleIds`, `expectedRevision`을 받는다. 선택 기사는 기존 이슈에서
`remove` 처리되고 새 수동 이슈에는 `add` 처리된다. 수동 이슈는 `manual_group=true`로
기록하며, 이후 자동 재군집화에서도 해당 수동 구성의 배타성을 다시 적용한다.
화면에서 기존 이슈 묶음을 선택하면 그 이슈의 유효 `articleIds` 전체를 요청에 포함한다.
따라서 기존 묶음끼리 또는 기존 묶음과 개별 기사를 선택하면 구성 전체가 하나의 새 수동
이슈로 합쳐지고, 이전 이슈에는 선택된 구성원이 남지 않는다.

```text
POST /api/cluster-runs
POST /api/cluster-runs/{cluster_run_id}/apply
```

첫 요청은 proposal과 diff를 만든다.

요청 본문은 `reportDate`, 선택적인 `asOf`, `similarityThreshold`를 받는다. `similarityThreshold`는 `0.15` 이상 `0.70` 이하이며 생략 시 `0.40`이다. 값이 낮을수록 넓게, 높을수록 엄격하게 묶는다. proposal의 `autoReasons.clustering`에는 실제 적용한 기준값을 기록한다.

- 생성 이슈
- 병합 후보
- 분할 후보
- 이동 기사
- 유지되는 editor override
- 수동 편집 이슈 중 자동 대응이 사라진 항목

`apply` 시에만 자동 필드와 자동 membership을 갱신한다.

화면의 `오늘 기사 검색`은 기사 수집이 성공하고 후보가 1건 이상이면 `similarityThreshold=0.15`로
proposal을 생성한 뒤 즉시 apply한다. 수집·목록 갱신·proposal 생성·apply 단계는 진행률로
표시한다. 자동 재군집화가 실패해도 이미 저장된 기사와 provider observation은 되돌리지 않으며,
수집 성공과 재군집화 오류를 함께 표시한다. 수동 `이슈 재군집화`는 기존 proposal 검토·적용
절차를 그대로 유지한다.

### 6.4 적용 규칙

- `editor_title`, `editor_status`, `editor_priority`는 절대 덮어쓰지 않는다.
- 수동 `add/remove` membership은 절대 삭제하지 않는다.
- 새 군집과 기존 이슈는 기사 집합 겹침, 대표 개체, 시간 범위로 매칭해 안정적인 `issue_id`를 재사용한다.
- 자동 대응이 사라진 수동 편집 이슈는 삭제하지 않고 `needs_review=true`로 표시한다.
- 최종 확정 snapshot의 이슈와 기사 구성은 재군집화의 영향을 받지 않는다.
- 재군집화는 `final` 작업본에 적용할 수 없다.

### 6.5 auto_status 전이와 spread_score 초기 산식

`auto_status`는 cluster run apply 시 유효 구성 기사의 보도시각으로 계산한다. `editor_status`가 있으면 화면 유효값은 항상 editor 값이며, 이 계산은 `auto_status`만 갱신한다.

```text
new        이슈 최초 생성 후 24시간 이내
expanding  최근 24시간 신규 기사 수 ≥ 2 이고 직전 24시간보다 증가
ongoing    최근 24시간 신규 기사 ≥ 1 이고 expanding 조건 미충족
cooling    최근 24시간 신규 기사 0건이고 마지막 기사 후 72시간 미만
closed     마지막 신규 기사 후 72시간 이상
```

`spread_score` 초기 산식은 다음과 같다. 계수는 Phase 6 fixture 검증에서 조정하되 산식 구조와 상한은 유지한다.

```text
spread_score = min(100,
    서로 다른 발행 매체 수 × 12
  + 주요 매체 1곳 이상 포함 시 20
  + 최근 24시간 신규 기사 수 × 8)
```

주요 매체 목록은 `config/classification_rules.yaml`에서 관리한다. 산식 입력값과 결과는 이슈의 자동 판정 근거에 기록한다.

---

## 7. JSON·CSV 왕복 계약

### 7.1 JSON

JSON은 정식 백업 형식이다.

- `schemaVersion` 필수
- 작업본, 기사 선정 상태, 중요 표시, 개별 기사 Top 이슈 태그, 메모, 수동 판정, 수집된 기사 전문과 수집 상태,
  이슈 편집값, AI run, action note를 포함한다.
- 가져오기 전 schema 검증을 수행한다.
- 내보내기→새 DB 가져오기→다시 내보내기의 의미상 동등성을 통합 테스트한다.
- 미지원 미래 version은 읽지 않고 명확한 오류를 반환한다.

#### JSON import 충돌 규칙

- 같은 `report_date`의 작업본이 이미 있으면 기본 동작은 거부다. `409 IMPORT_CONFLICT`와 함께 기존·가져오기 대상의 차이 요약을 반환한다.
- 사용자가 `mode=replace`를 명시하면 해당 날짜의 작업본과 편집 상태를 import 내용으로 교체한다. 교체 전 DB 자동 백업을 실행한다.
- 최종 snapshot은 불변이다. 같은 `(report_date, version)` snapshot이 이미 있고 내용이 동일하면 건너뛰고, 내용이 다르면 `mode`와 무관하게 `409 IMPORT_CONFLICT`다.
- 기사는 `content_key`가 일치하면 기존 `articles` row를 재사용하고 편집 상태만 연결한다. 일치하는 기사가 없으면 새로 생성한다.
- 어떤 경우에도 import가 다른 보고일의 데이터를 수정하지 않는다.

### 7.2 CSV

CSV는 목록 교환용이며 완전 백업 형식이 아니다.

- CSV로 AI 분석 이력, 최종 snapshot, 이슈 membership, 설정을 복원한다고 약속하지 않는다.
- 내보내기 화면에 “일부 필드만 포함”이라고 표시한다.
- 입력 셀이 `=`, `+`, `-`, `@`로 시작하면 spreadsheet formula 실행을 막기 위해 안전하게 escape한다.
- CSV import는 필드 mapping 결과와 누락 필드를 사용자에게 보여준 뒤 적용한다.

---

## 8. API 오류 코드 최소 집합

```text
BRIEFING_NOT_FOUND
BRIEFING_REVISION_CONFLICT
BRIEFING_FINALIZED
BRIEFING_VERSION_NOT_FOUND
ARTICLE_NOT_FOUND
ARTICLE_IN_USE
COLLECTION_PARTIAL
COLLECTION_FAILED
CLUSTER_RUN_NOT_FOUND
CLUSTER_RUN_STALE
AI_SCHEMA_INVALID
AI_EVIDENCE_INVALID
IMPORT_SCHEMA_UNSUPPORTED
IMPORT_CONFLICT
```
