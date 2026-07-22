# 기상 기반 전기재해 선제대응 브리핑 설계

- 문서 상태: 구현 전 설계 제안
- 작성 기준일: 2026-07-17
- 적용 대상: 현재 FastAPI + SQLite + HTML/CSS/ES Modules 구조
- 상위 계약: `docs/API_DATA_CONTRACTS.md`, `docs/ARCHITECTURE.md`

> 이 문서는 신규 기상 도메인의 구현안을 정리한다. 구현에 들어가기 전에
> `docs/API_DATA_CONTRACTS.md`와 `docs/ARCHITECTURE.md`에 확정 계약을 먼저 반영한다.

## 1. 결론

기상 기능은 기사 수집의 부가기능이 아니라 다음 세 축을 가진 독립 도메인으로 구현한다.

```text
기상청 원본 수집
→ 예보·특보 정규화
→ 규칙 기반 전기재해 위험 신호 생성
→ 담당자 검토 및 보고용 컨텍스트 첨부
→ CEO HTML·최종 snapshot·Gemma 입력에 반영
```

핵심 결정은 다음과 같다.

1. 기상예보와 특보를 `Article`이나 `Issue`로 저장하지 않는다.
2. 최신 기상정보는 화면에 자동 표시하되 CEO 보고에는 담당자가 검토해 첨부한
   기상 컨텍스트만 사용한다.
3. 기상 위험 단계는 서버의 버전 고정 규칙으로 계산하며 Gemma가 결정하지 않는다.
4. 공식 특보의 경보만 `critical`, 주의보·예비특보는 `watch`로 승격한다.
   수치예보만으로 `critical`을 만들지 않는다.
5. 기사 근거 `A01`과 기상 근거 `W01`을 분리한다. 기존 `articleIds`에 기상 ID를
   넣지 않는다.
6. 최종 확정 snapshot에는 당시 기상 컨텍스트와 근거를 통째로 복사한다.
7. 수집 실패 시 마지막 정상 데이터와 현재 오류·경과시간을 함께 표시한다.
   오래된 특보 상태를 근거로 “특보 없음”이라고 표시하지 않는다.

## 2. 범위

### 2.1 1차 포함

- 기상청 단기예보 D0~D3
- 기상청 중기예보 D4~D6
- 현재 기상특보와 예비특보
- 전국 및 7개 표시 권역의 7일 요약
- 규칙 기반 전기재해 위험 신호
- 편집 화면의 고시인성 기상 영역
- 담당자 검토·보고 반영 선택
- CEO 미리보기와 최종 보고 HTML
- 최종 snapshot과 JSON 정식 백업
- Gemma 입력 최신성 판정에 검토된 기상 컨텍스트 포함

### 2.2 1차 제외

- 지도 GIS 시각화
- 사업소별 시설·인력·비상근무 데이터 연계
- 기상정보만으로 자동 비상근무 확정
- SMS·메일·메신저 자동 발송
- Open-Meteo 등 민간·외국 API를 공식 근거로 사용
- 낙뢰 가능성 자동 판정

단기예보의 구조화 항목만으로는 낙뢰 위험을 안정적으로 판단하기 어렵다. 낙뢰는 향후
기상청 API허브의 낙뢰 관측·초단기 자료 또는 별도 검증된 데이터 계약을 추가한 뒤 구현한다.

## 3. 공식 데이터 소스

| 우선순위 | 용도 | 공식 서비스 | 사용 범위 |
|---|---|---|---|
| 1 | 현재 위험 | 기상청 기상특보 조회서비스 | 특보현황, 특보, 예비특보 |
| 2 | 단기 상세 | 기상청 단기예보 조회서비스 | `getVilageFcst`, D0~D3의 시간별 예보 |
| 3 | 중기 전망 | 기상청 중기예보 조회서비스 | `getMidLandFcst`, `getMidTa`, D4~D6 |
| 선택 | 전국 설명 | 기상청 중기전망 | 정형 카드의 보조 설명만 사용 |

공공데이터포털 서비스키는 `.env`의 `KMA_SERVICE_KEY`로만 읽는다. HTML, API 응답,
로그, JSON 백업에는 키를 기록하지 않는다. URL은 서버 코드의 허용 목록에 고정하고 사용자
입력 URL을 호출하지 않는다.

공식 서비스 참고:

- 단기예보: https://www.data.go.kr/data/15084084/openapi.do
- 중기예보: https://www.data.go.kr/data/15059468/openapi.do
- 기상특보: https://www.data.go.kr/data/15000415/openapi.do

## 4. 권역과 지점 모델

화면의 7개 권역은 조직도를 뜻하는 값이 아니라 기상 표시용 집계 권역이다.

```text
전국
수도권
강원권
충청권
호남권
영남권
제주권
```

권역 하나를 도시 한 곳의 예보로 대표하지 않는다. `config/weather_regions.yaml`에 다음을
버전 관리한다.

```yaml
version: weather-region-v1
regions:
  - id: capital
    label: 수도권
    shortForecastPoints:
      - id: seoul
        nx: 60
        ny: 127
      # 실제 운영 지점은 기상청 격자표로 검증 후 확정
    warningAreaCodes: []
    midLandCode: ""
    midTemperaturePoints: []
```

구현 전 다음 검증을 거친다.

- 단기예보 격자좌표는 기상청 최신 행정구역 격자표와 대조한다.
- 특보구역 코드는 기상청 최신 특보구역표와 대조한다.
- 각 표시 권역에는 최소 2개 이상의 대표 지점을 둔다.
- 실제 지역본부·사업소 관할과 연결할 때는 표시 권역과 별도 매핑을 추가한다.
- 권역 설정 버전을 기상 컨텍스트에 기록해 과거 결과를 재현한다.

전국 카드의 기온은 한 도시의 값이 아니라 대표 지점 전체의 최저~최고 범위로 표시한다.
강수 가능성은 해당 날짜 대표 지점·시간대의 최댓값으로 표시하고, 위험 지역 수는 위험 신호가
영향을 주는 표시 권역 수로 계산한다.

## 5. 백엔드 구성

```text
backend/app/
├─ api/weather.py
├─ repositories/weather_repository.py
└─ services/weather/
   ├─ kma_client.py
   ├─ normalizer.py
   ├─ region_config.py
   ├─ context_builder.py
   ├─ risk_engine.py
   └─ message_builder.py
```

- `kma_client.py`: 고정된 기상청 endpoint 호출, timeout, 오류 변환
- `normalizer.py`: KST 발표시각과 UTC 저장시각, 단위, 코드값 정규화
- `region_config.py`: 격자·특보구역·중기예보구역 매핑 로드 및 검증
- `context_builder.py`: provider별 최신 정상 데이터로 불변 기상 컨텍스트 생성
- `risk_engine.py`: 버전 고정 규칙으로 `WeatherRiskSignal` 생성
- `message_builder.py`: AI 없이도 사용할 수 있는 검증된 CEO 보고 문장 생성

기존 `urllib` 호출 방식을 재사용해 신규 런타임 의존성을 추가하지 않는다. 기상 수집은 기사
수집 실행과 별도 run으로 기록하고, 어느 한쪽 실패가 다른 쪽의 성공 상태를 바꾸지 않게 한다.

## 6. SQLite 설계

### 6.1 `weather_collection_runs`

```text
id
report_date
started_at
finished_at
status                 running | success | partial | failed
context_id
warning_count
error_count
created_at
```

### 6.2 `weather_run_providers`

```text
id
weather_collection_run_id
provider               kma_short | kma_mid | kma_alert | kma_pre_alert
status                  success | failed | stale_reused
issued_at
fetched_at
item_count
stale_from_observation_id
error_code
error_message
```

provider 일부 실패는 run 전체를 `partial`로 끝낸다. 성공한 provider 결과는 저장하고 실패한
provider는 마지막 정상 observation을 명시적으로 연결한다.

### 6.3 `weather_observations`

기상청의 원본 응답을 덮어쓰지 않고 요청 단위로 보존한다.

```text
id
weather_run_provider_id
provider
product
request_key
official_issued_at
observed_at
payload_json
payload_hash
```

서비스키와 서비스키가 포함된 원본 요청 URL은 저장하지 않는다.

### 6.4 `weather_contexts`

화면·검토·AI·최종보고에서 사용하는 불변 정규화 결과다.

```text
id
report_date
period_from
period_to
overall_level          critical | watch | info | normal | unknown
issued_at
built_at
region_config_version
risk_rule_version
source_status_json
daily_summaries_json
alerts_json
input_signature
created_at
```

같은 입력 서명은 중복 context를 만들지 않는다. `daily_summaries_json`은 화면에 필요한 7일
집계만 담고 원본 시간별 값은 observation에 보존한다.

### 6.5 `weather_risk_signals`

```text
id
weather_context_id
signal_key
hazard                 heavy_rain | typhoon | heat | strong_wind | snow
                       | cold | dry | humid | other
level                   critical | watch | info
starts_at
ends_at
region_ids_json
electrical_risks_json
recommended_checks_json
evidence_json
confidence             high | medium | low
rule_id
created_at
```

`evidence_json`에는 observation ID, 공식 발표시각, 특보 식별값 또는 예보 지점·시각을 넣는다.
AI 문장은 이 근거 밖의 지역·기간·수치를 만들 수 없다.

### 6.6 `briefing_weather`

최신 기상정보와 CEO 보고용 기상정보를 분리하는 핵심 association이다.

```text
briefing_id             PRIMARY KEY
weather_context_id
include_in_report
review_status           pending | reviewed
editor_note
attached_at
reviewed_at
updated_at
```

### 6.7 `briefing_weather_signals`

```text
briefing_id
weather_context_id
weather_risk_signal_id
selected
editor_level            NULL | critical | watch | info
editor_note
created_at
updated_at
PRIMARY KEY (briefing_id, weather_risk_signal_id)
```

자동 재수집은 이 표를 수정하지 않는다. 담당자가 해제한 신호도 `selected=false` row로 남긴다.
새 context를 첨부할 때는 새 신호를 `pending` 상태로 보여 주고, 담당자가 검토 완료해야 AI와
최종 보고에 반영한다.

## 7. API 계약 초안

### 7.1 최신 정보 조회와 수집

```text
GET  /api/weather/briefing?report_date=YYYY-MM-DD
POST /api/weather/refresh
GET  /api/weather/runs/{run_id}
```

`POST /api/weather/refresh` 요청:

```json
{
  "reportDate": "2026-07-17"
}
```

기상 수집은 브리핑 작업본을 변경하지 않으므로 `expectedRevision`을 받지 않는다.
수집 대상 `reportDate`는 서울 기준 오늘만 허용한다. 과거 보고일은 당시 저장된 context나
최종 snapshot을 조회하며, 현재 기상정보를 과거 보고일에 새로 연결하지 않는다.

`GET /api/weather/briefing` 응답 핵심 구조:

```json
{
  "latestContext": {
    "id": "weather-context-id",
    "issuedAt": "2026-07-17T06:00:00+09:00",
    "fetchedAt": "2026-07-17T06:12:00+09:00",
    "overallLevel": "watch",
    "period": {"from": "2026-07-17", "to": "2026-07-23"},
    "sourceStatus": {
      "alerts": {"status": "success", "issuedAt": "2026-07-17T06:10:00+09:00"},
      "shortForecast": {"status": "success", "issuedAt": "2026-07-17T05:00:00+09:00"},
      "midForecast": {"status": "stale", "issuedAt": "2026-07-16T18:00:00+09:00", "error": "..."}
    },
    "days": [],
    "riskSignals": []
  },
  "attached": {
    "contextId": "weather-context-id",
    "includeInReport": true,
    "reviewStatus": "reviewed",
    "selectedSignals": [
      {"id": "weather-signal-id", "selected": true, "editorLevel": null, "editorNote": ""}
    ]
  },
  "newerContextAvailable": false
}
```

### 7.2 보고용 기상 컨텍스트 검토

```text
PUT /api/briefings/{date}/weather
```

```json
{
  "expectedRevision": 12,
  "contextId": "weather-context-id",
  "includeInReport": true,
  "reviewStatus": "reviewed",
  "selectedSignals": [
    {
      "id": "weather-signal-id",
      "selected": true,
      "editorLevel": null,
      "editorNote": "충청권 취약시설 우선 확인"
    }
  ],
  "editorNote": "06시 발표 기준 검토"
}
```

- 현재 작업본이 없으면 `404 BRIEFING_NOT_FOUND`
- `expectedRevision` 불일치면 `409 BRIEFING_REVISION_CONFLICT`
- final 작업본이면 `409 BRIEFING_FINALIZED`
- 다른 context의 signal ID면 `400 WEATHER_SIGNAL_INVALID`
- stale 또는 오류 context도 첨부는 가능하되 응답과 화면에 경고를 유지한다.
- mutation 성공 시 브리핑 revision을 1 증가시킨다.
- 삭제 API를 만들지 않는다. 보고 제외는 `includeInReport=false`다.
- `includeInReport=true`인데 `reviewStatus=pending`이면 AI 분석과 finalize를
  `409 WEATHER_REVIEW_REQUIRED`로 거부한다.
- 기상 row가 없거나 `includeInReport=false`이면 기존 기사 브리핑 finalize를 막지 않는다.
- 더 최신 context가 생겨도 기존 첨부를 자동 교체하거나 자동으로 finalize를 막지 않고,
  `newerContextAvailable=true` 경고와 발표시각 차이를 보여 준다.

## 8. 수집과 최신성

### 8.1 실행 시점

- 앱 시작 시 비동기 1회
- 화면의 `기상정보 새로고침` 버튼
- 자동수집과 독립된 launchd 작업을 2시간 간격으로 실행
- 최종 확정 직전 특보 정보가 오래됐으면 새로고침을 권고

정확한 freshness 시간은 설정 파일에 두고 운영 검증 후 확정한다. 초기 제안은 다음과 같다.

| 소스 | fresh | stale 표시 | 의미 |
|---|---:|---:|---|
| 특보·예비특보 | 30분 이내 | 30분 초과 | 초과 시 “특보 없음” 판정 금지 |
| 단기예보 | 6시간 이내 | 6시간 초과 | 마지막 정상 예보와 오류 동시 표시 |
| 중기예보 | 18시간 이내 | 18시간 초과 | D4~D6 신뢰도 낮춤 |

### 8.2 일부 실패

```text
특보 성공 + 단기 실패 + 중기 성공
→ run.status = partial
→ 특보·중기는 신규값 사용
→ 단기는 마지막 정상값을 stale로 재사용
→ 화면과 보고에 단기예보 오류 표시
```

특보 조회가 stale이면 현재 특보 건수를 `0`으로 표시하지 않고 `확인 불가`로 표시한다.
마지막 정상 특보가 남아 있더라도 현재 발효 중이라고 단정하지 않는다.

## 9. 7일 예보 정규화

### 9.1 날짜 경계

- D0~D3: 사용 가능한 최신 단기예보
- D4~D6: 최신 중기 육상예보·기온예보
- 양쪽이 겹치면 발표시각이 유효한 단기예보를 우선
- 보고일과 날짜 표시는 `Asia/Seoul`
- DB의 수집·생성 시각은 UTC ISO 8601

### 9.2 일별 카드 값

```json
{
  "date": "2026-07-18",
  "weatherText": "비",
  "temperature": {"min": 22, "max": 31, "isNationalRange": true},
  "maxPrecipitationProbability": 80,
  "maxHourlyPrecipitation": {"text": "30.0~50.0mm", "min": 30.0, "max": 50.0, "unit": "mm/h"},
  "dailyPrecipitation": {"text": "120~200mm", "min": 120.0, "max": 200.0, "unit": "mm/day"},
  "riskLevel": "watch",
  "affectedRegionCount": 2,
  "source": "kma_short",
  "sourceIssuedAt": "2026-07-17T05:00:00+09:00"
}
```

대표 날씨는 위험 우선순위 `태풍/폭우 > 눈 > 비 > 흐림 > 맑음`으로 정하되, 이 값은 표시용이고
위험 단계를 직접 결정하지 않는다.

`maxHourlyPrecipitation`은 단기예보 `PCP`의 1시간 강수량 중 일 최대 구간이다. 일 누적
강수량으로 오인하지 않도록 화면에는 `시간당 예상 강수량`으로 표시하며, 중기예보처럼 원천에서
강수량을 제공하지 않는 구간은 임의 추정하지 않는다.

## 10. 전기재해 위험 규칙

### 10.1 단계

| 단계 | 생성 조건 | 보고 표현 |
|---|---|---|
| `critical` | 공식 기상경보 발효, 또는 복수 공식 경보 중첩 | 즉시 확인 필요 |
| `watch` | 공식 주의보, 예비특보, 검증된 단기 위험 규칙 | 선제 점검 필요 |
| `info` | D4~D6 중기 전망 또는 낮은 확신의 가능성 | 추이 확인 |
| `normal` | fresh한 모든 소스에서 신호 없음 | 별도 위험 신호 없음 |
| `unknown` | 핵심 소스 상태를 판단할 수 없음 | 기상정보 확인 필요 |

`normal`은 특보·단기예보의 최신성이 확인될 때만 사용한다.

### 10.2 위험 매핑

| 기상현상 | 전기안전 우려 | 권고 검토사항 |
|---|---|---|
| 호우·태풍 | 침수, 누전·감전, 옥외설비 손상 | 취약시설, 전원차단 안내, 비상연락체계 |
| 폭염 | 냉방설비 장시간 사용, 배선·접속부 과열 | 노후 배선, 멀티탭, 실외기 주변, 취약시설 |
| 강풍 | 옥외 임시전기설비·태양광설비 손상 | 옥외설비, 작업일정, 현장 작업자 안전 |
| 대설·한파 | 전열기기 과부하, 결빙·습설 | 전열기기, 옥외설비, 작업자 안전 |
| 건조 | 전기적 불꽃 발생 시 화재 확산 | 산림·야외시설 인접 설비 예방점검 |
| 고온다습 | 절연저하·누전 가능성 | 노후·습윤 취약시설 점검 |

이 표의 업무 범위와 표현은 안전정책·기술부서 검토 후 확정한다.

### 10.3 규칙 파일

`config/weather_risk_rules.yaml`은 다음 원칙을 가진다.

- `version` 필수
- 근거 source와 기상현상별 규칙 ID 필수
- `critical`은 공식 경보 규칙에서만 허용
- 수치 임계값은 단위와 적용 기간 필수
- 승인되지 않은 규칙은 `enabled: false`
- 계산 결과에 `rule_id`, `rule_version`, 입력 observation ID 기록

AI는 이 파일을 읽거나 수정하지 않는다.

## 11. 편집 화면 설계

언론브리핑의 화면 정체성을 유지하기 위해 KPI와 `오늘의 핵심 경영 메시지` 사이에는
특보와 주요 예보만 담은 `기상 특이사항` 요약을 둔다. 7일 예보, 권역 전환, 위험 신호 편집,
수집 및 CEO 보고 반영 기능은 `상세 기상정보·선제대응 검토` 모달에서 제공한다.

```text
┌──────────────────────────────────────────────────────────────────┐
│ 기상 특이사항                         [상세 기상정보 · 관리]    │
│ [주의 필요]  특보: 호우 주의 2건  주요 예보: 07-18 비         │
│ 최저·최고 19~33℃ · 시간당 예상 강수량 30~50mm/h · 확률 90%   │
│ 최신 정보 표시 중 · 보고 반영은 상세 화면에서 검토 후 확정     │
└──────────────────────────────────────────────────────────────────┘

상세 모달: 전국·6권역 위험도, D0~D6 카드, 최대 시간강수량·최고기온·최우선 지역,
provider별 발표시각과 오류, 현재·예비특보 공식 원문, 날짜별 6권역 기온·강수확률·시간강수량·풍속,
전체 위험 신호의 공식 근거·발효시각, 신호별 보고 반영·담당자 단계·메모,
새로고침과 CEO 보고 반영 검토.

상세 정보는 한 화면에 모두 노출하지 않고 `종합판단`, `특보·대응`, `권역비교` 탭으로 나눈다.
팝업을 열면 `종합판단`을 기본 표시하며, 긴 공식 원문과 편집 컨트롤은 `특보·대응`에만 둔다.

수치 강조는 상대 비교와 고정 표시 임계값을 함께 사용한다. 공식 경보, 시간강수량 30mm/h 이상,
35℃ 이상은 적색 계열로, 시간강수량 10mm/h 이상·강수확률 60% 이상·33℃ 이상은 주황 계열로
표시한다. 권역비교에서는 선택 날짜의 항목별 최댓값 셀을 별도로 강조하되, 동일 최댓값은 모두
표시한다. 강조색은 `집중호우`, `강한 비`, `고온`, `공식 경보` 텍스트 배지와 함께 사용한다.
```

### 11.1 시인성 원칙

- `critical`, `watch`, `info`, `normal`, `unknown`을 색상과 텍스트·아이콘으로 함께 구분
- 빨강만으로 경보를 표현하지 않고 `긴급`, `주의`, `확인 불가` 문구를 항상 표시
- 첫 화면에는 위험 상태, 주요 특보, 주요 예보와 판단용 핵심 수치(최저·최고기온,
  시간당 예상 강수량, 최고 강수확률)를 표시하고 위험 신호 편집은 상세 모달에 둠
- 상태·특보·예보·기온·강수량·강수확률은 텍스트와 인라인 SVG 아이콘을 함께 사용
- 특보 건수에는 영향 권역을 병기하고 현재특보와 예비특보를 분리해 표시
- 최고 위험 단계의 공식 특보 원문에서 시·군 단위 지역을 추려 `최우선 확인`으로 강조
- 7일 카드는 날짜, 대표 날씨, 기온 범위, 최대 강수확률, 위험 배지만 표시
- 모든 카드에 source 발표시각을 tooltip이 아닌 접근 가능한 텍스트로 제공
- stale 소스가 있으면 영역 상단을 황색 경고 상태로 유지
- 특보 source가 stale이면 “특보 0건” 대신 “특보 현재상태 확인 불가” 표시
- 외부 아이콘 CDN을 사용하지 않고 기존 SVG 방식 또는 CSS를 사용

### 11.2 화면 상태

1. `not-configured`: 서비스키 설정 안내, 마지막 데이터 없음
2. `loading`: 기존 정상 데이터는 유지하고 새로고침 진행 표시
3. `normal`: fresh한 소스에서 위험 신호 없음
4. `watch/critical`: 위험 신호와 우선 확인 지역 표시
5. `partial/stale`: 마지막 정상값 + 실패한 소스 + 경과시간 표시
6. `review-pending`: 최신값은 보이지만 CEO 보고에는 아직 미반영
7. `reviewed`: 첨부 context ID와 검토시각 표시
8. `newer-available`: 검토 후 더 최신 context가 생겼음을 경고

## 12. CEO 보고 HTML과 인쇄

읽기 전용 보고서는 1페이지의 언론 분석 다음, 하단에 `기상 기반 선제대응`
전용 section을 둔다.

```text
① 오늘 한줄
② 언론 동향 분석
③ 경영 참고사항
④ 기타 동향 (근거가 있을 때만)
기상 특이사항
붙임: 선정 기사 요약
```

기상 section에는 다음만 표시한다.

- 기상청 발표시각
- 위험 현상 후보 중 수치와 공식 신호를 기준으로 가장 중요한 1건만 표시
- 폭우는 `7. 19~20` 날짜·최대 시간당 강수량·일 최대 강수량·주요 권역을 표시
- 선택된 현상의 전기안전 우려를 같은 행에 함께 표시
- provider명·내부 상태값·오류 원문은 담당자용 상세 기상정보에만 표시하고 CEO 보고에서는 제외
- 강수확률, 종합 위험도, 긴급·주의 단계, 대응 권고문과 차순위 기상 현상은 보고서에 표시하지 않음

최종 snapshot은 첨부된 `weatherContext`, 선택된 `weatherRiskSignals`, 담당자 override,
source status, 근거 observation 메타데이터를 포함한다. 이후 최신 날씨가 바뀌어도 과거 최종
보고서는 바뀌지 않는다.

기상정보가 보고에서 제외되면 section을 빈 상태로 만들지 않고 생략한다. `unknown` 또는 수집
오류를 담당자가 검토할 때는 운영 화면에서 마지막 정상값과 오류를 함께 표시하되, CEO 보고에는
`midForecast: partial` 같은 provider명·내부 상태값·오류 원문을 인쇄하지 않는다.

## 13. CEO 문장 생성과 Gemma

### 13.1 1차 구현

1차는 서버 템플릿으로 문장을 만든다. 선택된 신호의 검증된 필드만 조합한다.

```text
{기간} {권역}에 {기상현상} {단계표현}에 따라 {전기안전 우려}에 대한
선제적 대비가 필요합니다. {권고 확인사항}을 우선 확인할 필요가 있습니다.
```

이를 통해 Ollama가 꺼져 있어도 기상정보가 CEO 보고에 들어간다.

### 13.2 Gemma 연계

기사 분석과 기상 분석을 같은 근거 배열로 섞지 않는다.

```json
{
  "weatherContext": {
    "contextId": "weather-context-id",
    "signature": "sha256...",
    "reviewedAt": "2026-07-17T06:20:00+09:00",
    "evidence": {
      "W01": "weather-signal-id"
    },
    "riskSignals": []
  }
}
```

기존 AI 결과의 `articleIds` 계약은 그대로 유지한다. 별도 필드를 추가한다.

```json
{
  "weatherManagementMessage": {
    "text": "",
    "weatherSignalIds": ["W01"]
  }
}
```

검증 규칙:

- 내용이 있으면 `weatherSignalIds` 1개 이상 필수
- 모든 ID는 해당 run의 고정 weather evidence에 존재
- 지역·기간·단계·수치는 연결된 신호에 존재해야 함
- `critical` 표현은 공식 경보 근거가 있는 신호만 허용
- 검증 실패 시 AI 기상 문장 전체를 버리고 서버 템플릿 문장을 사용
- 기사 분석 실패와 기상 문장 실패는 서로의 마지막 정상 결과를 삭제하지 않음

기상 컨텍스트 서명은 다음을 포함한다.

- context ID와 input signature
- provider별 공식 발표시각
- 선택된 signal ID
- 자동·담당자 최종 단계
- 영향 권역과 시작·종료시각
- 담당자 기상 메모
- region config version과 risk rule version

기상 컨텍스트가 변경되면 기존 AI 결과는 삭제하지 않고 stale로 표시한다. 자동 재분석으로
담당자 CEO 보고 편집본을 덮어쓰지 않는다.

## 14. JSON·CSV·초기화

- JSON 정식 백업 schema version을 올리고 모든 기상 테이블·association·최종 snapshot을 포함한다.
- JSON import는 weather context ID가 충돌하면 내용 hash를 비교한다.
- 같은 ID인데 내용이 다르면 `409 IMPORT_CONFLICT`로 거부한다.
- CSV는 기사 목록 교환 포맷이므로 기상 컨텍스트 복원을 약속하지 않는다.
- 오늘 작업 초기화는 `briefing_weather`, `briefing_weather_signals` 연결만 제거한다.
- 기상 원본 observation과 context는 감사·복구를 위해 초기화로 삭제하지 않는다.
- 최종 snapshot의 기상정보는 수정·삭제하지 않는다.

## 15. 오류 코드

```text
WEATHER_NOT_CONFIGURED
WEATHER_REFRESH_RUNNING
WEATHER_PROVIDER_FAILED
WEATHER_PARTIAL
WEATHER_CONTEXT_NOT_FOUND
WEATHER_RUN_NOT_FOUND
WEATHER_SIGNAL_INVALID
WEATHER_CONTEXT_STALE
WEATHER_REVIEW_REQUIRED
WEATHER_REGION_CONFIG_INVALID
WEATHER_RULE_CONFIG_INVALID
```

`GET` 응답은 마지막 정상 context와 현재 오류를 함께 반환한다. `POST refresh`가 실패했다고
마지막 정상 context를 삭제하지 않는다.

## 16. 구현 단계

리팩터링과 신규 기능을 섞지 않기 위해 아래 각 단계를 독립 작업으로 완료한다.

### 단계 A: 계약·fixture

- 상위 문서에 기상 계약 확정
- 공식 샘플 응답 fixture 확보
- 권역·특보구역·격자 설정 확정
- 안전정책·기술부서 위험 매핑 검토

### 단계 B: 수집·저장

- migration과 repository
- 기상청 client, 정상·timeout·잘못된 키·부분 실패 테스트
- 원본 observation과 마지막 정상 재사용
- 복구 절차와 JSON export 계약

### 단계 C: 정규화·위험 규칙

- D0~D6 날짜 연결
- 특보 lifecycle과 예비특보 정규화
- 위험 신호와 source evidence
- 경계시각·권역 중첩·stale 테스트

### 단계 D: 편집 화면

- KPI 아래 기상 영역
- 7일 카드와 권역 상세
- loading·partial·stale·unknown 상태
- 담당자 검토와 브리핑 첨부 mutation
- 인쇄용 축약 레이아웃

### 단계 E: CEO 보고·snapshot

- 미리보기와 최종 HTML section
- 불변 snapshot·버전·JSON round-trip
- 보고 제외·오류 포함·재확정 테스트

### 단계 F: Gemma

- `Wxx` 근거 index와 별도 weather schema
- 입력 서명과 stale 처리
- 서버 자동 검증과 템플릿 fallback
- 외부 AI Markdown·보고 편집본 계약 확장

### 단계 G: 운영 자동화

- 독립 weather launchd job
- 설정 누락·장애 로그
- 백업·복구 runbook
- 실제 아침 보고 시간대 운영 검증

## 17. 필수 테스트

### 단위 테스트

- 단기·중기·특보 JSON 정상화
- 자정·KST/UTC·발표시각 경계
- D3/D4 source 연결
- 권역 지점 집계
- 공식 경보/주의보/예비특보 단계
- 경보 없는 수치예보가 `critical`을 만들지 않음
- stale 특보가 `normal`이나 “0건”을 만들지 않음
- 담당자 `selected=false`, `editor_level`, 메모 보존
- 기상 입력 서명 변경
- `Wxx` 근거 ID 검증

### 통합 테스트

- provider 일부 실패 후 마지막 정상 데이터 보존
- 최신 context 갱신이 검토 완료 association을 덮어쓰지 않음
- `expectedRevision` 충돌
- final 작업본 mutation 거부
- preview와 final snapshot의 기상정보 동일성
- reopen 후 새 context로 v2 확정해도 v1 불변
- JSON export/import round-trip
- AI 기상 검증 실패 시 템플릿 fallback

### 수동 회귀

기존 `docs/MANUAL_REGRESSION_CHECKLIST.md` 전체에 다음을 추가한다.

- 기상 정상·설정 누락·부분 실패·stale 상태
- 7일 카드 날짜·권역 전환·상세 펼치기
- 보고 반영 전/후와 최신 context 존재 경고
- 특보 `critical`/`watch` 시인성 및 키보드 접근
- CEO 미리보기·최종본·A4 인쇄 첫 페이지
- 기사 선택·메모·AI 분석·JSON/CSV 기존 기능 회귀 없음

## 18. 구현 전 확정할 사항

1. 공공데이터포털 서비스키 발급 주체와 운영 키 보관 위치
2. 7개 표시 권역의 대표 격자·특보구역 코드
3. 안전정책·기술부서가 승인한 위험-전기재해-권고사항 매핑
4. 예보 수치 임계값을 1차에 사용할지, 공식 특보 중심으로 시작할지
5. 아침 보고 직전 허용할 특보 freshness 시간
6. CEO 보고에서 기상 section을 항상 표시할지, 신호가 있을 때만 표시할지

권장 기본값은 `공식 특보 중심으로 시작`, `신호 또는 오류가 있을 때 section 표시`,
`수치 임계값은 부서 승인 전 비활성`이다.
