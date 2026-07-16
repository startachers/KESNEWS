# 기사 수집 설계 변경 (v2)

- 문서 상태: 구현 지시 가능 설계
- 기준 코드: 2026-07-16, Phase 9 완료 시점 (`backend/` FastAPI + SQLite + `frontend/` 정적 ES Modules)
- 선행 문서: `docs/ARCHITECTURE.md`, `docs/API_DATA_CONTRACTS.md`, `docs/KNOWN_RISKS.md`(P4-001·P4-006)
- 주의: 이 문서의 모든 수정 대상은 **현행 백엔드·프런트 코드**다.
  `legacy/kesco_media_briefing_original.html`은 읽기 전용 참고물이며 절대 수정하지 않는다.

## 담당자가 체감할 변화 (요약)

이 변경이 끝나면 홍보실 담당자 화면은 이렇게 달라진다.

```text
1. 검색 설정이 6개 → 17개가 되고, 5개 그룹 제목 아래 정리되어 표시된다.
   필요 없는 검색군은 지금처럼 체크 해제로 끌 수 있다.
2. 대통령·총리·장관 발언, 정부회의, 국회, 경영평가 기사가 새로 들어온다.
3. 전국의 사망 화재·대규모 정전 속보가 원인 확인 전에도 들어오고,
   '원인 미상 화재' 배지로 구분된다. 전기 원인이 확인되면 배지가 바뀐다.
4. 기사는 신뢰 언론사 20곳 + 정부·공공기관 공식자료만 저장된다.
   걸러진 건수는 수집 결과 화면에 함께 표시된다.
5. 계획정전 안내, 예방 캠페인 기사는 사고로 잘못 분류되지 않는다.
6. 처음 실행할 때 기존 검색 설정은 자동으로 새 구조로 바뀌며,
   조회기간·키워드 등 일반 설정은 그대로 유지된다.
```

---

# 1. 변경 목적

현재 언론브리핑은 6개 검색식만 사용한다.

```text
기관 직접 / 전기화재·감전 / 기후·에너지 정책 / 경영·감사 / 지역·상생 / 재생에너지
```

이 구조는 검색 범위가 좁아 다음 정보를 놓칠 수 있다.

```text
대통령·대통령실의 정책 메시지
국무총리·총리실의 정책 메시지
기후에너지환경부 장관 발언
국무회의·관계장관회의·정부위원회 결정
공공기관 경영평가 및 운영정책
공사 경영·거버넌스 이슈
국회·국정감사·법안
전기 원인 미확인 중대화재 속보
정전·전력공급 장애
ESS·배터리·충전시설 등 신산업 설비안전
법령·기준·기본계획
전력망·분산에너지·데이터센터 등 전략동향
```

따라서 기존 6개 검색식에 일부를 추가하는 것이 아니라,
**기사 검색식 전체를 17개 검색군으로 교체한다.**

---

# 2. 최종 기사 검색군 17개

```text
1. 공사 직접 보도            (kesco_direct)
2. 공사 위기·평판            (kesco_reputation)
3. 대통령·대통령실 메시지    (presidential_message)
4. 국무총리·총리실 메시지    (prime_minister_message)
5. 기후에너지환경부 장관 메시지 (climate_minister_message)
6. 국무회의·관계장관회의·정부위원회 (government_meeting)
7. 공공기관 경영평가         (public_evaluation)
8. 공공기관 운영정책         (public_operations)
9. 공사 경영·거버넌스        (kesco_governance)
10. 국회·국정감사·법안       (assembly_law)
11. 전기화재·감전 사고       (electrical_accident)
12. 정전·전력공급 장애       (power_outage)
13. 중대화재·원인 미상 속보  (major_fire_breaking)
14. ESS·배터리·충전시설 등 신산업 설비안전 (new_industry_safety)
15. 법령·기준·기본계획       (law_standard_plan)
16. 공사 성과·상생·예방활동  (kesco_achievement)
17. 전력망·분산에너지·데이터센터 등 전략동향 (strategic_trend)
```

`정전`과 `중대화재`는 일반 사고 검색에 묶지 않고 각각 별도 검색군으로 둔다.

기존 6개 검색식은 다음과 같이 흡수한다.

| 기존 | 변경 후 |
|---|---|
| 기관 직접 | 공사 직접 보도 |
| 전기화재·감전 | 전기화재·감전 사고 |
| 기후·에너지 정책 | 대통령·총리·장관·정부회의·법령·전략동향으로 분리 |
| 경영·감사 | 공사 위기·평판, 공공기관 경영평가·운영정책, 공사 경영·거버넌스로 분리 |
| 지역·상생 | 공사 성과·상생·예방활동 |
| 재생에너지 | 신산업 설비안전, 전략동향으로 분리 |

---

# 3. 검색식 정의 (Google News RSS 기준 원본)

아래 검색식이 **정본(canonical)** 이다. Google News RSS는 `OR`·따옴표·괄호를
지원하므로 그대로 실행한다. 네이버 API는 이 문법을 지원하지 않으므로
§12의 변환 규칙을 별도로 적용한다.

`{OR_current_*}` 토큰은 §5의 인물 치환 규칙을 따른다.

```js
queries: [
  { id: "kesco_direct", label: "공사 직접 보도", enabled: true,
    query: '("한국전기안전공사" OR "전기안전공사" OR "KESCO")' },

  { id: "kesco_reputation", label: "공사 위기·평판", enabled: true,
    query: '("한국전기안전공사" OR "전기안전공사" OR "KESCO") (사망 OR 사고 OR 화재 OR 감전 OR 정전 OR 중대재해 OR 부실점검 OR 허위점검 OR 위반 OR 논란 OR 수사 OR 고발 OR 압수수색 OR 징계 OR 비위 OR 해킹 OR "정보 유출" OR 민원)' },

  { id: "presidential_message", label: "대통령·대통령실 메시지", enabled: true,
    query: '("대통령실" OR "대통령"{OR_current_president}) ("전기안전" OR 전력망 OR 전력수급 OR 전기설비 OR 전기화재 OR 감전 OR 정전 OR ESS OR "전기차 충전") (지시 OR 주문 OR 당부 OR 강조 OR 브리핑 OR 업무보고 OR 대책)' },

  { id: "prime_minister_message", label: "국무총리·총리실 메시지", enabled: true,
    query: '("국무총리" OR "총리실" OR "국무조정실"{OR_current_prime_minister}) ("전기안전" OR 전력망 OR 전력수급 OR 전기설비 OR 전기화재 OR 감전 OR 정전) (지시 OR 주문 OR 당부 OR 강조 OR 회의 OR 현안조정 OR 대책)' },

  { id: "climate_minister_message", label: "기후에너지환경부 장관 메시지", enabled: true,
    query: '("기후에너지환경부"{OR_current_climate_minister}) (전기안전 OR 전력망 OR 전력수급 OR 전기설비 OR 전기화재 OR 감전 OR 정전 OR ESS OR "전기차 충전" OR 재생에너지) (발언 OR 지시 OR 주문 OR 당부 OR 브리핑 OR 업무보고 OR 현장점검 OR 대책)' },

  { id: "government_meeting", label: "국무회의·관계장관회의·정부위원회", enabled: true,
    query: '("국무회의" OR "국정현안관계장관회의" OR "경제관계장관회의" OR "공공기관운영위원회" OR "에너지위원회" OR "전력정책심의회") (전기안전 OR 전력 OR 전력망 OR 전력수급 OR 전기설비 OR 정전 OR 공공기관)' },

  { id: "public_evaluation", label: "공공기관 경영평가", enabled: true,
    query: '("공공기관 경영실적 평가" OR "공공기관 경영평가" OR "경영평가편람" OR "경영평가 결과" OR "경영실적 평가결과")' },

  { id: "public_operations", label: "공공기관 운영정책", enabled: true,
    query: '("공공기관" OR "공기업" OR "준정부기관") ("공공기관운영위원회" OR "예산운용지침" OR 총인건비 OR 직무급 OR 성과급 OR "안전관리등급" OR 경영공시 OR ALIO)' },

  { id: "kesco_governance", label: "공사 경영·거버넌스", enabled: true,
    query: '("한국전기안전공사" OR "전기안전공사" OR "KESCO") (경영평가 OR 경영공시 OR 국정감사 OR 감사원 OR 이사회 OR 기관장 OR 사장 OR 상임감사 OR 임원 OR 인사 OR 노사 OR 노조 OR 파업 OR 예산 OR 총인건비 OR 직무급 OR 성과급)' },

  { id: "assembly_law", label: "국회·국정감사·법안", enabled: true,
    query: '(국회 OR 국정감사 OR 국정조사 OR 법안 OR 개정안 OR 입법예고 OR 현안질의) (전기안전 OR 전기화재 OR 감전 OR 정전 OR 전력망 OR 전기설비 OR "한국전기안전공사")' },

  { id: "electrical_accident", label: "전기화재·감전 사고", enabled: true,
    query: '("전기화재" OR "전기 화재" OR "누전 화재" OR "전기적 요인" OR "감전사고" OR "감전 사고" OR "감전 사망" OR "배전반 화재" OR "변압기 화재")' },

  { id: "power_outage", label: "정전·전력공급 장애", enabled: true,
    query: '("대규모 정전" OR "광역 정전" OR "일대 정전" OR "전력 공급 중단" OR "전력망 장애" OR "계통 장애" OR 블랙아웃 OR "변전소 고장" OR "송전선로 고장" OR "배전선로 고장")' },

  { id: "major_fire_breaking", label: "중대화재·원인 미상 속보", enabled: true,
    query: '(화재 OR 폭발 OR 큰불) (사망 OR 숨져 OR 사상 OR 중상 OR 심정지 OR 실종 OR 전소 OR 대피 OR "대응 1단계" OR "대응 2단계" OR "대응 3단계")' },

  { id: "new_industry_safety", label: "ESS·배터리·충전시설 등 신산업 설비안전", enabled: true,
    query: '(ESS OR "에너지저장장치" OR 배터리 OR "전기차 충전") (화재 OR 감전 OR 폭발 OR 사고 OR 안전점검 OR 결함 OR 리콜)' },

  { id: "law_standard_plan", label: "법령·기준·기본계획", enabled: true,
    query: '("전기안전관리법" OR "전기사업법" OR "한국전기설비규정" OR KEC OR "전기설비기술기준" OR "전기안전관리 기본계획" OR "전력수급기본계획") (개정 OR 시행 OR 입법예고 OR 행정예고 OR 고시 OR 확정 OR 발표)' },

  { id: "kesco_achievement", label: "공사 성과·상생·예방활동", enabled: true,
    query: '("한국전기안전공사" OR "전기안전공사" OR "KESCO") (업무협약 OR 협약 OR 수상 OR 혁신 OR 합동점검 OR 특별점검 OR 예방점검 OR 캠페인 OR 봉사 OR 기부 OR 상생 OR 안전문화 OR 취약계층)' },

  { id: "strategic_trend", label: "전력망·분산에너지·데이터센터 등 전략동향", enabled: true,
    query: '("전력망" OR "송전망" OR "배전망" OR "분산에너지" OR "데이터센터" OR "재생에너지" OR "전력수요") (전기안전 OR 안전관리 OR 전기설비 OR 화재 OR 정전 OR 검사 OR 규제 OR 기본계획)' }
]
```

작성 원칙:

- 검색식 하나는 최대 3개 괄호 그룹(AND)까지만 쓴다. Google News RSS의
  긴 쿼리 절단을 피하기 위해 그룹당 OR 항목은 20개를 넘기지 않는다.
- `kesco_reputation`처럼 기관명 그룹이 포함된 검색군은 기관명 그룹을
  항상 첫 그룹에 둔다.

---

# 4. 검색군 관련도 우선순위 (신규 — 반드시 이 표를 따른다)

`get_relevance()`의 현행 5단계 rank를 아래 7단계로 교체한다.
rank는 **기사 텍스트 기준**으로 판정하며, 정렬·절단·표시에 공통 사용한다.

| rank | 판정 기준 (제목+본문 텍스트) | 대응 검색군 | label |
|---:|---|---|---|
| 1 | 기관명 직접 거론 (`한국전기안전공사`/`전기안전공사`/`KESCO`) | kesco_direct, kesco_reputation, kesco_governance, kesco_achievement | 매우 높음 |
| 2 | 전기화재·감전 사고 표현 | electrical_accident | 높음 |
| 3 | 정전·전력공급 장애 표현, 또는 사고 Sentinel 일치(§6·§7) | power_outage, major_fire_breaking | 높음 |
| 4 | 대통령·총리·장관·정부회의·국회 + 전기·에너지 문맥 | presidential/prime_minister/climate_minister_message, government_meeting, assembly_law | 보통 |
| 5 | 전기 관련 법령·기준·기본계획 | law_standard_plan | 보통 |
| 6 | 공공기관 경영평가·운영정책 일반 | public_evaluation, public_operations | 관심 |
| 7 | 신산업 설비안전·전략동향 | new_industry_safety, strategic_trend | 관심 |
| 99 | 기준 미일치 | — | 낮음 |

- 점수 배분: rank 1=100, 2=88, 3=80, 4=65, 5=55, 6=45, 7=40. 제목 일치 +7,
  복수 기준 일치 +2/건(최대 +5), 상한 99(rank 1만 100). tier 경계(`related`≥40)는 유지한다.
- **Sentinel 일치 기사는 텍스트가 다른 rank 기준에 걸리지 않아도 rank 3으로 처리한다.**
  rank 99로 떨어져 정렬 최하위 → `collectionLimit` 절단으로 소실되는 것을 막기 위함이다.

---

# 5. 현직 인물 자동 치환

대통령·국무총리·기후에너지환경부 장관 이름을 검색식에 하드코딩하지 않는다.

**현재 프로젝트에 인물 설정은 존재하지 않으므로 신규 파일을 만든다**:
`config/people.yaml` (+ `config/people.example.yaml`을 저장소에 커밋, 실파일
취급은 기존 config 파일 관례에 맞춤)

```yaml
version: 1
people:
  president: ""          # 현직 대통령 이름. 빈 값 허용
  prime_minister: ""
  climate_minister: ""
```

치환은 **백엔드 수집 직전에** 수행한다. 수동 검색(localStorage 설정)과
launchd 자동수집(`config/automated_collection.json`)이 같은 경로를 타도록,
`backend/app/services/collection/collector.py`의 `run_collection()` 진입부에서
query 문자열을 치환한다.

토큰 규칙 — 빈 값일 때 `OR ""` 찌꺼기가 남지 않도록 **OR 절 단위 토큰**을 쓴다:

```text
{OR_current_president}        → 값 있음: ' OR "홍길동"' (설정된 이름) / 값 없음: '' (빈 문자열)
{OR_current_prime_minister}   → 동일
{OR_current_climate_minister} → 동일
```

치환값이 없으면 이름 절만 사라지고 직책 검색어는 그대로 유지된다.

---

# 6. 중대화재 Sentinel 수집 기준

중대화재 검색군(`major_fire_breaking`)은 전기 원인이 확인되지 않아도 수집한다.

판정 함수: `backend/app/services/classification/sentinel.py` (신규) —
`detect_incident_sentinel(article) -> {"matched": bool, "incident": {...}}`

화재 Sentinel 일치 조건 — **화재 신호어 + 중대성 신호어가 함께 있으면 일치**:

```text
화재 신호어: 화재, 큰불, 폭발, 진화
중대성 신호어: 사망, 숨져, 사상, 중상, 심정지, 실종, 전소, 반소,
              대피, 연기흡입, 재산피해, 피해액,
              "대응 1단계", "대응 2단계", "대응 3단계"
중요시설어:   병원, 요양병원, 학교, 유치원, 공항, 철도, 지하철, 데이터센터,
              발전소, 변전소, 산업단지, 물류센터, 전통시장, 지하주차장,
              ESS, 전기차 충전
```

**수치 미상 시 기본 동작(중요)**: 사망자 수·피해액이 기사에 없어도
신호어 조합이 맞으면 **일단 수집**한다. 수치는 추출 가능할 때만 채우고,
불가능하면 `null`로 남긴다. "재산피해 3억원 이상" 같은 임계값은
**수치가 명시된 경우에만** 필터로 쓰고, 미상이면 수집을 유지한다.

최초 수집 시 incident 정보:

```json
{
  "incident_type": "fire",
  "cause_status": "unknown",
  "incident_status": "breaking",
  "deaths": null,
  "injuries": null,
  "property_damage_krw": null,
  "critical_facility": null
}
```

전기적 원인이 확인되기 전에는 `전기화재`로 표시하지 않는다.
(배지: `원인 미상 화재` → 원인 보도 시 `전기 원인 의심`/`전기 원인 확인`)

---

# 7. 정전 Sentinel 수집 기준

정전 Sentinel 일치 조건:

```text
정전 신호어: 정전, 전력 공급 중단, 블랙아웃, 변전소 고장,
            송전선로 고장, 배전선로 고장, 계통 장애
동반 신호어(하나 이상): 세대, 가구, 병원, 공항, 철도, 지하철, 데이터센터,
            신호등, 승강기, 산업단지, 공장, 생산 차질, 화재, 폭발, 감전, 복구
```

**계획정전 제외 규칙**: 아래 표현이 있고 실제 사고 신호어가 없으면 제외한다.

```text
계획정전 / 정전 예정 / 정전 안내 / 정기점검에 따른 / 전기공사로 인한 /
정전 대비 훈련 / 정전 예방
```

수치(정전 세대 수, 지속 시간)는 추출 가능할 때만 `incident_json`에 채우고,
미상이면 `null`로 두되 수집은 유지한다(§6과 동일 원칙).

```json
{
  "incident_type": "outage",
  "incident_status": "breaking",
  "households": null,
  "duration_minutes": null,
  "critical_facility": null,
  "planned": false
}
```

---

# 8. 수집 파이프라인 변경 (단일 정본 순서)

전체 처리 순서는 아래 **하나**로 통일한다. §14(허용목록)·§12(네이버)를
포함한 모든 절이 이 순서를 따른다.

```text
① 수집 (네이버 API → 연합 RSS → Google RSS → GDELT 보조)
② 정규화 (제목·URL·발행일)
③ 공식자료 판별 → 공식자료면 허용목록 건너뛰고 보존
④ 신뢰 언론사 허용목록 검사 → 탈락 기사 제거 + 통계 기록
⑤ 사고 Sentinel 판정 (중대화재·정전)
⑥ 관련도 판정 (17개 검색군 rank, §4)
⑦ Sentinel 일치 또는 rank < 99 → 보존, 그 외 제거
⑧ 제외어·조회기간 필터, 중복 제거
⑨ collectionLimit 절단 — 단, Sentinel 일치·rank 1 기사를 먼저 채운 뒤
   나머지를 관련도순으로 채운다
⑩ 분류·위험도 판정 → 이슈 군집화 → 브리핑 후보
```

실제 코드 수정 지점:

- `backend/app/services/collection/yonhap.py:20` —
  현행 `items = [item for item in items if get_relevance(item)["rank"] < 99]` 를
  Sentinel 판정 선행으로 교체:

```python
items = [
    item for item in items
    if detect_incident_sentinel(item)["matched"]
    or get_relevance(item)["rank"] < 99
]
```

- `backend/app/services/collection/collector.py` —
  `classified_items.sort(...)` 후 `[:collection_limit]` 절단(현행 238–239행)을
  ⑨의 보호 규칙으로 교체. `collectionLimit` 기본값을 200 → **400**으로 올린다
  (17개 검색군 × 최대 50건 대응).
- `get_relevance()`는 기사 삭제를 결정하는 **유일한** 필터로 쓰지 않는다.

---

# 9. 분류 체계 변경

- `primary_category`: 기사 내용 판정 결과(단일). `rule_engine.py`의
  `_CATEGORY_RULES`를 17개 검색군 id 기준으로 재작성한다.
- `matched_query_ids`: **신규 저장 구조를 만들지 않는다.**
  기존 `article_observations` 테이블이 이미 기사별 `query_group_id`를
  수집 경로마다 기록하고 있으므로, API 응답·내보내기에서
  observations를 집계해 도출한다.

```json
{
  "primary_category": "power_outage",
  "matched_query_ids": ["power_outage", "government_meeting"]
}
```

검색식은 기사를 발견한 경로이고, 최종 분류는 기사 내용 판정 결과다.

DB 변경 (`backend/app/db/migrations/0008_query_groups_17.sql` 신규):

```sql
-- article_assessments에 사고 정보 1개 컬럼만 추가 (넓은 스키마 금지)
ALTER TABLE article_assessments ADD COLUMN incident_json TEXT;
-- 언론사 판별 결과 (§14)
ALTER TABLE articles ADD COLUMN publisher_id TEXT;
ALTER TABLE articles ADD COLUMN publisher_allowed INTEGER;
```

---

# 10. 수정 대상 파일·함수 매핑표 (정본)

| 영역 | 파일 | 수정 내용 |
|---|---|---|
| 검색식 기본값 | `frontend/js/state/store.js` | `DEFAULT_SETTINGS.queries` 17개 교체, `settingsVersion: 3`, `CATEGORY_COLORS` 17개 확장 |
| 설정 마이그레이션 | `frontend/js/state/store.js` `loadSettings()` | §11 규칙 |
| 검색 설정 화면 | `frontend/js/ui/dialogs.js` `renderQuerySettings()` | 17개 행 + §13 그룹 헤더 |
| 필터·수동 분류 | `frontend/js/ui/dialogs.js`·`app.js` `populateStaticControls()` | 17개 분류 반영 |
| 기사 카드 배지 | `frontend/js/ui/renderers.js` | §13 배지 |
| 프런트 관련도 표시 | `frontend/js/features/collection.js` `getRelevance()` | 서버 저장값(`article.assessment`) 우선 사용, 로컬 재계산은 §4 기준으로 동기화 |
| 수집 오케스트레이션 | `backend/app/services/collection/collector.py` | 인물 치환(§5), 절단 보호(§8-⑨), 허용목록(§14), 네이버 provider 연결(§12) |
| 연합 RSS | `backend/app/services/collection/yonhap.py` | Sentinel 선행 필터(§8) |
| Google RSS | `backend/app/services/collection/google_news.py` | `<source url>` 도메인 추출(§14) |
| GDELT | `backend/app/services/collection/gdelt.py` | 실패 검색군 검색식 기반 보조 검색으로 확장, 허용목록 동일 적용 |
| 네이버 API | `backend/app/services/collection/naver_news.py` (신규) | §12 |
| Sentinel | `backend/app/services/classification/sentinel.py` (신규) | §6·§7 |
| 관련도·분류 | `backend/app/services/classification/rule_engine.py`, `service.py` | §4 rank 체계, `_CATEGORY_RULES` 17개, `CLASSIFIER_VERSION`을 `rules-v3`으로 증가 |
| 언론사 판별 | `backend/app/services/media.py` | `identify_trusted_publisher()` 추가(§14) — `is_yonhap_article` 옆 |
| JSON 내보내기 | `backend/app/services/exports/json_export.py` | `primary_category`·`matched_query_ids`·`incident_json` 보존, `schemaVersion` 증가 |
| CSV 내보내기 | `backend/app/services/exports/csv_export.py` | §15 열 추가, import 왕복 유지(P4-006) |
| 자동수집 설정 | `config/automated_collection.json` | **17개 검색식으로 교체 (누락 금지)** |
| 검색식 예시 | `config/search_rules.example.yaml` | 17개 기준으로 갱신 |
| 신규 설정 | `config/people.yaml`, `config/trusted_media.yaml` | §5, §14 |

주의: 관련도 로직이 프런트(`collection.js`)와 백엔드(`service.py`)에
중복 구현되어 있다. **판정의 정본은 백엔드**이며, 프런트는 API가 반환한
평가값을 표시에 사용한다. 두 구현이 남는 동안 rank 기준은 §4 표 하나로 동기화한다.

---

# 11. 설정 마이그레이션

## 11.1 localStorage (수동 검색 설정)

`DEFAULT_SETTINGS.settingsVersion`을 2 → 3으로 올린다.
기존 `loadSettings()`의 버전 마이그레이션 분기(현행 로직 재사용)에 따라:

```text
저장된 settingsVersion < 3
→ 일반 설정값 보존: autoRun, enableYonhap, lookback, maxRecords,
  collectionLimit, endpoint, coreKeywords, riskKeywords,
  positiveKeywords, excludeKeywords
→ queries는 신규 17개 기본값으로 재생성
→ 같은 id가 있는 항목만 enabled 상태 승계 (기존 6개 id는 모두 소멸하므로
  실질적으로 전부 신규 기본값 enabled=true)
→ settingsVersion=3 저장
```

마이그레이션이 실행된 첫 화면에서 담당자에게 한 번만 안내한다
(기존 toast 사용): `"기사 검색식이 17개 검색군으로 개편되었습니다.
검색 설정에서 확인해 주세요."` — 기존에 꺼두었던 검색식이 있었다면
모두 켜진 상태로 초기화되므로, 이 안내 없이 조용히 바꾸지 않는다.

기존 6개 검색식 문자열을 신규 검색식에 덮어쓰지 않는다.
(`proxy`는 현행 코드가 이미 삭제하는 필드이므로 보존 목록에 넣지 않는다.)

## 11.2 자동수집 설정 (누락하면 안 되는 지점)

launchd 2시간 주기 자동수집은 localStorage가 아니라
**`config/automated_collection.json`을 읽는다.** 이 파일의 `queries` 6개를
신규 17개로 교체하지 않으면 수동 검색과 자동수집이 서로 다른 검색식으로
돌아가는 이중 상태가 된다. 반드시 함께 교체하고,
`config/search_rules.example.yaml`도 동일 기준으로 갱신한다.

## 11.3 후속 과제 (이번 범위 아님, 기록만)

검색식이 localStorage와 `automated_collection.json` 두 곳에 존재하는 것은
KNOWN_RISKS **P4-001**(설정 서버 일원화, `/api/settings` 미구현)의 결과다.
이번 작업으로 17개 검색식이 두 곳에 복제되므로, P4-001 해소 시
이 문서의 검색식 정의(§3)를 단일 원본으로 이관한다.
KNOWN_RISKS에 본 작업과의 연관을 추가 기록한다.

---

# 12. 네이버 뉴스 검색 API 연동

## 12.1 원칙

- 화면 크롤링이 아니라 공식 뉴스 검색 API(`GET https://openapi.naver.com/v1/search/news.json`)를 쓴다.
- 인증정보는 **백엔드 환경변수로만** 읽는다: `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET`.
  HTML·프런트 JS·JSON 내보내기·화면 오류 메시지에 절대 노출하지 않는다.
  launchd 자동수집에서도 읽을 수 있도록 plist EnvironmentVariables 또는
  기존 실행 스크립트의 env 로딩에 반영한다(`install_launchd.command` 확인).
- 언론사 판별은 `link`(`n.news.naver.com`)가 아니라 **`originallink`를 우선** 사용한다.

## 12.2 검색식 변환 규칙 (필수 — §3 검색식을 그대로 보내면 안 된다)

네이버 뉴스 API의 `query`는 단순 검색어이며 Google식 `OR`·괄호 불리언을
지원하지 않는다. 따라서 검색군마다 **네이버용 단순 쿼리 목록**을 별도 정의한다.

- `DEFAULT_SETTINGS.queries[i]`에 `naverQueries: string[]` 필드를 추가한다.
  각 항목은 공백 AND만 사용하는 단순 검색어 1개다.
- 검색군당 최대 3개로 제한한다(호출량 관리). 예시:

```js
{ id: "kesco_direct", ...,
  naverQueries: ["한국전기안전공사", "전기안전공사"] },
{ id: "power_outage", ...,
  naverQueries: ["대규모 정전", "변전소 고장", "전력 공급 중단"] },
{ id: "presidential_message", ...,
  naverQueries: ["대통령 전력망", "대통령 전기안전", "대통령실 전력수급"] }
```

- 호출량 상한 검증: 17개 군 × 최대 3개 = 회당 최대 51호출.
  2시간 주기 자동수집 기준 일 612호출로 일일 한도(25,000)에 여유가 있다.

## 12.3 요청·정규화

```http
GET /v1/search/news.json?query={단순검색어}&display=100&start=1&sort=date
X-Naver-Client-Id / X-Naver-Client-Secret 헤더
```

- 네이버 API는 기간 필터가 없으므로 `pubDate`가 lookback 경계를 벗어날 때까지
  `start`를 100씩 증가시키며 최대 3페이지까지 추가 조회한다.
- 응답 항목을 기존 Article 형식으로 정규화한다:

```python
def normalize_naver_item(item: dict, query_id: str) -> dict:
    return {
        "title": clean_html(item.get("title", "")),
        "url": item.get("originallink") or item.get("link") or "",
        "naverUrl": item.get("link") or "",
        "pubDate": parse_naver_date(item.get("pubDate")),   # RFC 1123 → ISO 8601
        "description": clean_html(item.get("description", "")),
        "provider": "네이버 뉴스 API",
        "_query_group_id": query_id,
    }
```

동일 기사가 여러 검색군에 잡히면 제거하지 말고 observation을 각각 기록한다
(기존 `_upsert_article_for_item` + `insert_observation` 경로가 이미 이렇게 동작한다).

## 12.4 수집원 우선순위·장애 대응

```text
1. 정부·국회·공공기관 공식 원문
2. 네이버 뉴스 검색 API
3. 연합뉴스 공식 RSS
4. Google 뉴스 RSS
5. GDELT 보조 (fallback_only 유지)
```

- 동일 기사의 대표 URL 선택: 언론사 원문 URL > 네이버 originallink >
  언론사 RSS URL > Google 중계 URL > GDELT URL.
- 네이버 API 실패(인증·한도·시간초과) 시 전체 수집을 실패 처리하지 않고
  RSS 경로로 계속 진행하며 `warnings`에 상태만 남긴다.
  화면 표시는 세 가지로 한정: `네이버 뉴스 API 연결됨 / 미설정 / 오류`.
- `config/sources.example.yaml`의 providers 구조에 맞춰 항목을 추가한다:

```yaml
  naver_news:
    enabled: true
    type: naver_news_api
    priority: 15        # yonhap(10)과 google_news(20) 사이
    fallback_only: false
    timeout_seconds: 15
    display: 100
    max_pages: 3
```

---

# 13. 검색 설정 화면·배지

## 13.1 검색 설정 화면 (17개 행, 그룹 고정)

```text
[기관·평판]      공사 직접 보도 / 공사 위기·평판
[정부 메시지]    대통령·대통령실 / 국무총리·총리실 / 기후에너지환경부 장관 / 국무회의·정부위원회
[공공기관 경영]  공공기관 경영평가 / 공공기관 운영정책 / 공사 경영·거버넌스 / 국회·국정감사·법안
[사고·안전]      전기화재·감전 사고 / 정전·전력공급 장애 / 중대화재·원인 미상 속보 / 신산업 설비안전
[제도·성과·전략] 법령·기준·기본계획 / 공사 성과·상생·예방활동 / 전략동향
```

체크박스를 해제하면 해당 검색식만 실행하지 않는다.

## 13.2 기사 카드 배지

```text
검색군: 공사 직접 / 공사 위기 / 공사 거버넌스 / 대통령 메시지 / 총리 메시지 /
        장관 메시지 / 정부 회의 / 경영평가 / 공공기관 정책 / 국회·법안 /
        전기화재 / 감전 / 정전 사고 / 신산업 설비안전 / 법령·기준 /
        성과·예방 / 전략동향
사고:   원인 미상 화재 / 전기 원인 의심 / 전기 원인 확인
출처:   정부 원문 / 국회 원문 / 법령 원문 / 공사 원문
우선도: 보고필수 / 검토 / 참고 (기존 유지)
```

---

# 14. 신뢰 언론사 20개 허용목록

## 14.1 적용 원칙

일반 언론기사는 검색 결과에 포함됐다는 이유만으로 저장하지 않는다.
파이프라인 §8-③④ 위치에서 적용한다. 이 목록은 절대적 품질 순위가 아니라
KESCO 언론브리핑 운영용 허용목록이며, `config/trusted_media.yaml`에서
담당자가 추가·삭제할 수 있어야 한다.

## 14.2 기본 허용 언론사 20개

| 언론사 | 유형 | 허용 도메인 |
|---|---|---|
| 연합뉴스 | 뉴스통신 | `yna.co.kr` |
| 뉴스1 | 뉴스통신 | `news1.kr` |
| 뉴시스 | 뉴스통신 | `newsis.com` |
| KBS | 지상파 | `kbs.co.kr` |
| MBC | 지상파 | `imbc.com` |
| SBS | 지상파 | `sbs.co.kr` |
| JTBC | 종편 | `jtbc.co.kr` |
| YTN | 보도전문 | `ytn.co.kr` |
| 한겨레 | 종합일간지 | `hani.co.kr` |
| 경향신문 | 종합일간지 | `khan.co.kr` |
| 한국일보 | 종합일간지 | `hankookilbo.com` |
| 중앙일보 | 종합일간지 | `joongang.co.kr` |
| 동아일보 | 종합일간지 | `donga.com` |
| 조선일보 | 종합일간지 | `chosun.com` |
| 서울신문 | 종합일간지 | `seoul.co.kr` |
| 국민일보 | 종합일간지 | `kmib.co.kr` |
| 세계일보 | 종합일간지 | `segye.com` |
| 매일경제 | 경제지 | `mk.co.kr` |
| 한국경제 | 경제지 | `hankyung.com` |
| 전자신문 | 산업·IT 전문지 | `etnews.com` |

## 14.3 설정 파일 `config/trusted_media.yaml`

```yaml
version: 1
media_source_policy:
  mode: allowlist_only
  unknown_publisher_action: reject
  use_original_link_domain: true

trusted_media:
  - { id: yonhap,      name: 연합뉴스,  domains: [yna.co.kr] }
  - { id: news1,       name: 뉴스1,    domains: [news1.kr] }
  - { id: newsis,      name: 뉴시스,   domains: [newsis.com] }
  - { id: kbs,         name: KBS,      domains: [kbs.co.kr] }
  - { id: mbc,         name: MBC,      domains: [imbc.com] }
  - { id: sbs,         name: SBS,      domains: [sbs.co.kr] }
  - { id: jtbc,        name: JTBC,     domains: [jtbc.co.kr] }
  - { id: ytn,         name: YTN,      domains: [ytn.co.kr] }
  - { id: hani,        name: 한겨레,   domains: [hani.co.kr] }
  - { id: khan,        name: 경향신문, domains: [khan.co.kr] }
  - { id: hankookilbo, name: 한국일보, domains: [hankookilbo.com] }
  - { id: joongang,    name: 중앙일보, domains: [joongang.co.kr] }
  - { id: donga,       name: 동아일보, domains: [donga.com] }
  - { id: chosun,      name: 조선일보, domains: [chosun.com] }
  - { id: seoul,       name: 서울신문, domains: [seoul.co.kr] }
  - { id: kmib,        name: 국민일보, domains: [kmib.co.kr] }
  - { id: segye,       name: 세계일보, domains: [segye.com] }
  - { id: mk,          name: 매일경제, domains: [mk.co.kr] }
  - { id: hankyung,    name: 한국경제, domains: [hankyung.com] }
  - { id: etnews,      name: 전자신문, domains: [etnews.com] }

approved_incident_media: []   # 중대사고 보조 언론, 담당자가 직접 추가할 때만 허용
```

## 14.4 공식자료 예외

정부·국회·공공기관 공식자료는 언론사가 아니므로 허용목록과 별도로 수집한다.
**아래 도메인은 배포 전 실제 접속으로 재확인한다** (조직 개편으로 변동 가능).

```yaml
official_source_exemptions:
  - president.go.kr       # 대통령실
  - opm.go.kr             # 국무조정실·국무총리비서실
  - me.go.kr              # 기후에너지환경부 (확인 필요)
  - moef.go.kr            # 기획재정부
  - motie.go.kr           # 산업통상자원부
  - korea.kr              # 대한민국 정책브리핑
  - assembly.go.kr
  - likms.assembly.go.kr
  - alio.go.kr
  - law.go.kr
  - kesco.or.kr
```

중대사고 공식 출처 예외:

```yaml
incident_official_sources:
  - nfa.go.kr             # 소방청
  - police.go.kr          # 경찰청
  - mois.go.kr            # 행정안전부
  - kepco.co.kr           # 한국전력공사
  - kpx.or.kr             # 전력거래소
```

허용목록 밖 일반 지역 언론은 중대사고라도 자동 수집하지 않는다.
필요하면 담당자가 `approved_incident_media`에 직접 추가한다.

## 14.5 언론사 판별 규칙 (수집원별 도메인 출처)

언론사 이름 문자열이 아니라 **원문 URL 도메인**으로 판별한다.
구현 위치: `backend/app/services/media.py`.

수집원별 도메인 출처 — 이 규칙이 없으면 Google·GDELT 기사가 전부 탈락한다:

| 수집원 | 판별 도메인 |
|---|---|
| 네이버 API | `originallink` 도메인. `originallink` 없고 `link`가 `n.news.naver.com`이면 `unknown_publisher` → reject |
| 연합뉴스 RSS | 항상 `yna.co.kr` → 자동 허용 |
| Google 뉴스 RSS | 기사 링크는 `news.google.com` 중계 URL이므로 쓰지 않는다. RSS 항목의 `<source url="...">` 값을 도메인으로 사용. source 태그 없으면 reject |
| GDELT | 기사 URL 도메인. 국내 허용목록과 거의 겹치지 않아 대부분 탈락함을 **의도된 동작**으로 명시 (GDELT는 fallback_only 유지) |

```python
def normalize_hostname(raw_url: str) -> str:
    try:
        host = urlparse(raw_url).hostname or ""
        return host.lower().removeprefix("www.")
    except ValueError:
        return ""

def domain_matches(hostname: str, allowed: str) -> bool:
    return hostname == allowed or hostname.endswith(f".{allowed}")
```

수집 통계에 제외 건수를 기록하고 화면에 표시한다:

```json
{
  "source_filter_stats": {
    "raw_results": 240,
    "official_sources": 18,
    "trusted_media": 96,
    "rejected_untrusted_media": 126,
    "unknown_publisher": 0
  }
}
```

---

# 15. 내보내기 변경

## JSON (`json_export.py`)

- `primary_category`, `matched_query_ids`(observations 집계), `incident_json`,
  `publisher_id`, `publisher_allowed`를 보존한다.
- `schemaVersion`을 1 올리고 이전 버전 import 호환을 유지한다(기존 관례).
- 네이버 인증정보가 어떤 형태로도 포함되지 않는지 테스트로 확인한다.

## CSV (`csv_export.py`)

`HEADERS`에 추가:

```text
주분류, 검색일치항목, 사고유형, 사고상태, 원인상태,
사망, 부상, 재산피해, 정전세대, 정전시간, 중요시설, 계획정전, 언론사ID
```

- 값이 미상이면 빈 칸으로 내보낸다.
- export → import 왕복이 기존 검증(P4-006, LEG-005 관련 테스트)과 동일하게
  유지되어야 한다. 신규 열도 왕복 대상이다.

---

# 16. 테스트 사례

## 16.1 검색군 판정

| 입력 기사 | 기대 결과 |
|---|---|
| 한국전기안전공사, 전통시장 합동점검 | kesco_direct + kesco_achievement (matched_query_ids 병합) |
| 전기안전공사 점검 부실 논란 | kesco_reputation, rank 1 |
| 대통령, 전력망 확충 주문 | presidential_message, rank 4 |
| 총리, 여름철 전력수급 점검회의 | prime_minister_message |
| 기후부 장관, ESS 화재대책 강조 | climate_minister_message + new_industry_safety |
| 국무회의서 전기안전관리법 개정안 의결 | government_meeting + law_standard_plan |
| 공공기관 경영평가 결과 발표 | public_evaluation |
| 감전사고로 작업자 사망 | electrical_accident, rank 2 |
| 아파트 1,500세대 정전 | power_outage Sentinel 일치, households=1500 |
| 공장 화재 1명 사망, 원인 조사 중 | major_fire_breaking Sentinel 일치, cause_status=unknown, rank 3 |
| 창고 화재, 피해 규모 파악 중 (수치 없음) | Sentinel 일치, deaths=null — **수집 유지** |
| 정기점검에 따른 계획정전 안내 | 계획정전 제외 |
| 전기화재 예방 합동점검 | 사고 아님, 예방활동 (기존 예방/사고 분리 로직 유지) |

## 16.2 허용목록·네이버

| 테스트 | 기대 결과 |
|---|---|
| 연합뉴스·KBS·전자신문 원문 | 허용 |
| 허용목록 밖 인터넷 언론 | 제외 + rejected 통계 증가 |
| 네이버 결과: link=n.news.naver.com, originallink=yna.co.kr | 연합뉴스로 판별 |
| 네이버 결과: originallink 없음 | unknown_publisher → 제외 |
| Google RSS: source url=chosun.com | 조선일보로 판별 |
| Google RSS: source 태그 없음 | 제외 |
| 대통령실·국회·소방청 공식자료 | 언론사 필터 없이 허용 |
| 허용목록 밖 지역 언론의 중대화재 속보 | 자동 허용하지 않음 |
| approved_incident_media 등록 매체 | 등록된 경우에만 허용 |
| 네이버 API 인증 실패 | RSS 경로로 계속 수집, 화면에 "네이버 뉴스 API 오류", 키 미노출 |
| 동일 기사가 네이버+Google에서 수집 | 기사 1건, observation 2건, matched_query_ids 병합 |
| settingsVersion 2 localStorage | 17개로 재생성, 일반 설정 보존 |
| automated_collection.json | 17개 검색식 포함 확인 |

---

# 17. 완료 기준

```text
 1. 검색 설정 화면이 신규 17개 검색군을 그룹 헤더와 함께 표시하고 개별 on/off 된다.
 2. config/automated_collection.json과 localStorage 기본값이 모두 17개로 교체된다.
 3. settingsVersion 2 → 3 마이그레이션이 일반 설정을 보존한다.
 4. 인물 토큰이 백엔드에서 치환되고, 빈 값이면 OR 절이 흔적 없이 제거된다.
 5. 연합 RSS에서 Sentinel 일치 기사가 rank 99여도 살아남는다.
 6. collectionLimit 절단에서 Sentinel·rank 1 기사가 우선 보존된다.
 7. 수치 미상 중대화재·정전 속보가 신호어 기준으로 수집된다(수치는 null).
 8. 계획정전 안내는 사고로 수집되지 않는다.
 9. 원인 미확인 화재는 '전기화재'로 표시되지 않는다.
10. 일반 언론기사는 trusted_media.yaml 허용목록 통과분만 저장된다.
11. 공식자료(official/incident 도메인)는 허용목록과 별도로 저장된다.
12. Google RSS 기사가 <source url> 기준으로 판별된다.
13. 네이버 API가 백엔드에서 naverQueries 변환 쿼리로 호출된다.
14. NAVER_CLIENT_ID/SECRET이 HTML·JS·JSON 내보내기·오류 메시지에 노출되지 않는다.
15. 여러 수집원·검색군 중복 기사가 기사 1건 + observation N건으로 정리된다.
16. 수집 화면에 허용/제외 건수(source_filter_stats)가 표시된다.
17. JSON·CSV 내보내기가 신규 필드를 포함해 왕복(import)된다.
18. 기존 기사 선택·중요 표시·메모·AI 요약·finalize 기능이 회귀 없이 유지된다.
```

---

# 18. 구현 단계 분할 (한 번에 구현하지 않는다)

이 프로젝트의 Phase 원칙(체크포인트별 구현→테스트→커밋, KNOWN_RISKS 갱신)에
따라 아래 4단계로 나눠 진행한다. 각 단계는 독립적으로 완결되고 테스트된다.

```text
단계 1. 17개 검색군 교체
  - §3 검색식, §4 rank 체계, §5 인물 치환, §11 마이그레이션(양쪽 모두),
    §13.1 설정 화면, CATEGORY_COLORS·필터, CLASSIFIER_VERSION rules-v3
  - 완료 기준 1~4

단계 2. 사고 Sentinel + 파이프라인 순서
  - §6·§7 sentinel.py, §8 yonhap 선행 필터·절단 보호, §9 incident_json
    (migration 0008), §13.2 사고 배지, §15 내보내기
  - 완료 기준 5~9, 17

단계 3. 신뢰 언론사 허용목록
  - §14 trusted_media.yaml, media.py 판별, Google source url 추출,
    공식자료 예외, source_filter_stats
  - 완료 기준 10~12, 16

단계 4. 네이버 뉴스 API provider
  - §12 naver_news.py, naverQueries 변환, env 로딩(launchd 포함),
    우선순위·장애 대응
  - 완료 기준 13~15
```

완료 기준 18(기존 기사 선택·중요 표시·메모·AI 요약·finalize 회귀 없음)은
**모든 단계 공통**이며, 각 단계의 커밋 전에 통합 테스트로 확인한다.

## 이번 작업에서 제외

```text
새 AGENTS.md 작성 / 새 프로젝트 생성 / 기존 프로젝트 구조 변경
자동 스케줄러 신규 구현 (Phase 9 launchd 기존 구조 재사용)
React·Vue 전환 / UI 전체 재설계 / Gemma 분석 전면 개편
/api/settings 도입 (P4-001 — §11.3에 후속 기록만)
```

---

# 19. 작업 지시문

```text
기존 프로젝트의 AGENTS.md, README.md, docs/ARCHITECTURE.md,
docs/API_DATA_CONTRACTS.md와 현재 개발 단계(Phase 9 완료)를 우선 준수한다.

new_rules_news_clip.md(이 문서)를 읽고 §18의 단계 순서대로 구현한다.
한 단계를 구현·테스트·커밋한 뒤 다음 단계로 넘어간다.

주의사항:
1. 수정 대상은 §10 매핑표의 현행 backend/·frontend/ 파일이다.
   legacy/kesco_media_briefing_original.html은 절대 수정하지 않는다.
2. config/automated_collection.json의 검색식 교체를 누락하지 않는다.
3. 네이버 API에는 §3 검색식을 그대로 보내지 않고 §12.2 naverQueries를 쓴다.
4. 관련도 판정의 정본은 backend/app/services/classification/service.py이며
   프런트 getRelevance는 서버 평가값을 우선 사용하도록 바꾼다.
5. Sentinel 일치 기사는 관련도 필터와 collectionLimit 절단 양쪽에서
   보호되어야 한다(§8-⑦⑨).
6. 각 단계 완료 시 docs/KNOWN_RISKS.md에 해소/후속 항목을 기록하고
   docs/CODEX_NEXT_TASK.md를 갱신한다.

각 단계 구현 후 보고:
1. 변경 파일  2. 해당 단계 완료 기준 충족 여부(§17 번호로)
3. 테스트 결과(pytest·ruff·node --check)  4. 남은 위험 또는 미구현 사항
```
