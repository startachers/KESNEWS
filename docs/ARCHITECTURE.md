# KESCO 일일 언론브리핑 로컬 웹앱 아키텍처

- 문서 상태: 기준 설계
- 설계 버전: 1.2
- 운영 환경: 로컬 Mac 단독 사용
- 사용자: 홍보실 담당자 1인
- 기본 주소: `http://127.0.0.1:8787`
- 핵심 기술: HTML/CSS/JavaScript, FastAPI, SQLite, Ollama
- 구현 전 필수 계약: `docs/API_DATA_CONTRACTS.md`

---

## 1. 목표

기존 단일 HTML의 장점을 유지하면서 다음 업무를 한 흐름으로 처리한다.

```text
기사 수집
→ 정규화·중복 제거
→ 관련도·사안 판별
→ 동일 이슈 묶기
→ 담당자 선별·메모
→ Gemma 분석
→ 담당자 수정
→ CEO 보고 HTML·PDF
→ 날짜별 보관·복구
```

기상 기반 선제대응은 기사 흐름과 독립적으로 다음 파이프라인을 가진다.

```text
기상청 예보·특보 수집
→ 원본 observation 보존
→ 7일 기상 context 정규화
→ 규칙 기반 전기재해 위험 신호
→ 담당자 검토·브리핑 첨부
→ CEO 보고 snapshot
```

최신 기상 context와 보고에 첨부된 context를 구분한다. 자동 수집은 최신 context만 추가하며
이미 검토된 브리핑 association을 바꾸지 않는다.
서비스키가 설정된 경우 앱 시작 시 비동기로 한 번 갱신하며, 기사 자동수집과 분리된
launchd 작업이 2시간 간격으로 같은 refresh API를 호출한다.

1차 완성 목표는 “기능이 많은 플랫폼”이 아니라 다음 조건을 만족하는 안정적인 로컬 업무도구다.

- Mac에서 원클릭 실행된다.
- 브라우저가 닫혀도 데이터는 SQLite에 남는다.
- 기사 수집 실패 원인을 확인할 수 있다.
- 예방 보도를 사고 보도로 오분류하는 문제를 줄인다.
- 동일 사건의 여러 기사를 하나의 이슈로 볼 수 있다.
- AI 결과에 근거 기사가 연결된다.
- 담당자가 수정한 결과는 자동 작업으로 덮어쓰지 않는다.
- 최종 보고 화면은 편집 화면과 분리된다.

---

## 2. 범위

### 포함

- 연합뉴스 RSS, Google 뉴스 RSS, GDELT 보조 수집
- 기사 직접 추가, JSON·CSV 가져오기
- 기사 정규화, 완전 중복 제거, 유사 중복 판별
- 관련도, 보도 성격, 보고 우선도 분류
- 동일 사건 기사 군집화
- 브리핑 기사 선정, 중요 표시, 메모
- Ollama 기반 구조화 분석
- 날짜별 브리핑 저장
- 읽기 전용 CEO 보고 HTML
- 브라우저 인쇄를 통한 PDF 저장
- 자동 백업과 실행 로그
- macOS 원클릭 실행 및 후속 `launchd` 자동수집

### 1차 범위 제외

- 외부 서버·클라우드 배포
- 기관 업무망 연계
- 계정·로그인·권한
- 다중 사용자 동시 편집
- 모바일·아이패드 지원
- React, Vue 등 프런트엔드 프레임워크 전환
- Docker
- 자동 이메일·메신저 발송
- 상용 뉴스 데이터 계약 연동
- 완전 자동 최종보고 확정

---

## 3. 설계 원칙

### 3.1 기존 화면을 버리지 않는다

현재 HTML의 레이아웃, 기사 선택, 메모, 요약 수정, 인쇄 경험을 기준으로 삼는다. 초기 리팩터링은 기능과 디자인을 바꾸지 않는다.

### 3.2 브라우저는 업무 화면이다

최종 구조에서 브라우저 JavaScript가 직접 RSS를 읽거나 위험도를 계산하거나 영구 저장하지 않는다.

```text
프런트엔드: 표시, 입력, 필터, API 호출
백엔드: 수집, 정규화, 분류, 군집화, AI, 보고 생성
SQLite: 기사, 이슈, 브리핑, 실행 이력
```

### 3.3 기사·이슈·브리핑을 분리한다

- **기사(Article)**: 언론사가 게시한 원본 보도
- **이슈(Issue)**: 같은 사건을 다룬 여러 기사 묶음
- **브리핑(Briefing)**: 특정 보고일에 담당자가 확정한 보고 내용

기사에 `selected`, `starred`, `note`를 직접 저장하지 않는다. 이 값들은 보고일마다 달라질 수 있으므로 브리핑-기사 연결 정보로 저장한다.

### 3.4 자동 판정과 담당자 최종값을 분리한다

자동 분류 결과와 수동 수정값을 같은 필드로 덮어쓰지 않는다.

```text
자동 판정: auto_priority, auto_category, auto_event_type
담당자 최종: final_priority, final_category, final_event_type
```

최종값이 없을 때만 자동값을 화면에 사용한다.

언론기사의 `weather` 자동 분류는 호우·태풍·폭염·한파·대설 등 기상 관련 보도를 뜻한다.
기상 원인 기사라도 제목에 실제 정전이 확인되면 `power_outage`, 화재·감전이 확인되면 해당
사건 분류를 우선한다. 이는 기상청 observation/context 저장 구조와 독립적이며 자동 재분류는
담당자의 `final_category`를 덮어쓰지 않는다.

### 3.5 규칙 우선, AI 보조

기사 전체를 매번 LLM에 보내 분류하지 않는다.

1. 명시적 규칙으로 빠르게 분류
2. 경계 사례만 선택적으로 AI 보조
3. 최종 선정 기사만 고품질 AI 분석

브리핑 기사 추천도 같은 원칙을 따른다. 기존 분류·군집 검토점수로 후보를 최대 60건까지
압축한 뒤 Gemma가 공사 직접성·법정업무 연관성을 우선해 핵심 6건과 추가 참고 6건, 최대
12건을 추천한다. 유효 후보가 12건 이상이면 정확히 12건을 강제하고, 후보 자체가 부족할 때만
후보 수만큼 추천한다. 최종 출처 판정이
`kesco_republication` 또는 `kesco_based`인 공사 보도자료 전재·기반 기사는 압축 전 후보에서
제외한다. 개별 지자체·소방서의 저심각도 예방 홍보처럼 지역에만 국한된 일상 활동도 제외하되,
실제 사고·인명피해·광역 영향이 있는 지역 기사는 유지한다. 전기적 원인이나 공사 업무 연결이
없는 일반 화재는 제외하고, 해외 사고는 국내 제도·설비·대응 또는 공사 해외사업과의 구체적
연결이 있을 때만 유지한다. 1~6위는 공사 관련성 품질 gate를 적용하고, 7~12위는 CEO의 경영
시야를 위한 정부부처·거시경제·AI 일반 중요 동향을 허용한다. 공사 직접 언급이 없다면
제목도 전기·에너지·화재 안전 주제와 일치해야 하며, 종합기사 본문의 부수적 관련 단락만으로
후보에 포함하지 않는다. 동일 이슈는 규칙 점수가 가장 높은 대표 1건으로 제한한다. 추천 실행과
`briefing_articles.selected` mutation은 분리하며 담당자의 명시적 적용 전에는 작업본을
변경하지 않는다. 적용 시 기존 수동 선정과 메모·중요·Top Issue·분류 override를 보존하면서
추천 기사에 `briefing_articles.selected=true`만 적용한다. Top Issues는 추천 적용과 분리해
담당자가 Media Coverage에서 수동으로 관리하며, 추천 적용은 군집의
`briefing_issues.selected`나 개별 기사의 `briefing_articles.top_issue`를 변경하지 않는다.
기존 버전에서 군집 기사에 직접 저장된 Top 태그는 migration 0016에서 군집 태그로 승격한다.
화면과 상한 계산도 군집 구성 기사의 잔여 태그를 해당 군집 하나로 합산해, 비활성 버튼과
`TOP_ISSUE_LIMIT_EXCEEDED`가 동시에 나타나는 상태를 방지한다.
후보 압축 이후에도 서버 응답 검증에서 동일 이슈 ID 중복과 제목-핵심주제 불일치를 다시 검사한다.
따라서 Gemma가 프롬프트를 따르지 않아도 해당 응답은 작업본에 적용할 수 없다.

### 3.6 실패를 숨기지 않는다

수집 실패 시 기존 기사를 삭제하지 않는다. 마지막 정상 수집 시각과 실패 원인을 함께 표시한다.

### 3.7 작은 단계로 전환한다

단일 HTML 분리, 서버 도입, 수집 이전, SQLite 이전을 각각 독립 단계로 수행한다. 한 단계의 회귀검증이 끝나기 전에 다음 단계로 넘어가지 않는다.

### 3.8 API·데이터 계약을 먼저 고정한다

백엔드와 DB 구현 전에 `docs/API_DATA_CONTRACTS.md`의 계약을 따른다. 특히 다음 항목은 구현 중 임의로 바꾸지 않는다.

- 보고일별 작업본과 최종 version 선택 규칙
- 선택 해제·숨김·물리 삭제의 의미
- provider 관측과 수집 실행 이력 보존
- 분류 점수·임계값·문맥 충돌 순서
- AI 모든 주장 필드의 근거 ID 검증
- 재군집화 시 담당자 override 보존

이 문서와 상세 계약이 충돌하면 상세 계약이 우선한다.

---

## 4. 시스템 구성

```text
┌──────────────────────────────────────────────┐
│ macOS                                        │
│                                              │
│  Safari/Chrome                               │
│  ┌────────────────────────────────────────┐  │
│  │ HTML/CSS/ES Modules                    │  │
│  │ 편집 화면 / CEO 보고 화면             │  │
│  └───────────────────┬────────────────────┘  │
│                      │ HTTP / JSON            │
│  ┌───────────────────▼────────────────────┐  │
│  │ FastAPI 127.0.0.1:8787                │  │
│  │ API · 수집 · 판별 · 군집 · AI · 보고  │  │
│  └───────┬───────────────┬────────────────┘  │
│          │               │                   │
│  ┌───────▼────────┐  ┌───▼────────────────┐  │
│  │ SQLite         │  │ Ollama             │  │
│  │ app.db         │  │ Gemma 계열 모델    │  │
│  └────────────────┘  └────────────────────┘  │
│          │                                   │
│  ┌───────▼────────────────────────────────┐  │
│  │ reports / backups / logs               │  │
│  └────────────────────────────────────────┘  │
└──────────────────────────────────────────────┘
          │
          ▼
연합뉴스 RSS / Google 뉴스 RSS / GDELT / 기사 원문
```

---

## 5. 목표 저장소 구조

> 아래는 최종 목표 구조다. 첫 작업에서 모든 빈 파일을 한꺼번에 만들지 않는다. 기능이 해당 계층으로 이동할 때 필요한 파일만 생성한다.

```text
kesco-media-briefing/
├─ AGENTS.md
├─ README.md
├─ CHANGELOG.md
├─ pyproject.toml
├─ .env.example
├─ .gitignore
├─ setup_kesco_briefing.command
├─ start_kesco_briefing.command
│
├─ docs/
│  ├─ ARCHITECTURE.md
│  ├─ API_DATA_CONTRACTS.md
│  ├─ KNOWN_RISKS.md
│  ├─ MANUAL_REGRESSION_CHECKLIST.md
│  ├─ REFACTORING_MAP.md
│  └─ CODEX_NEXT_TASK.md
│
├─ legacy/
│  └─ kesco_media_briefing_original.html
│
├─ frontend/
│  ├─ index.html
│  ├─ report.html
│  ├─ css/
│  │  ├─ tokens.css
│  │  ├─ app.css
│  │  └─ print.css
│  └─ js/
│     ├─ app.js
│     ├─ api/
│     │  └─ client.js
│     ├─ state/
│     │  └─ store.js
│     ├─ features/
│     │  ├─ articles.js
│     │  ├─ issues.js
│     │  ├─ briefing.js
│     │  ├─ settings.js
│     │  ├─ ai-analysis.js
│     │  └─ exports.js
│     ├─ ui/
│     │  ├─ renderers.js
│     │  ├─ dialogs.js
│     │  └─ notifications.js
│     └─ utils/
│        ├─ dates.js
│        ├─ dom.js
│        └─ format.js
│
├─ backend/
│  └─ app/
│     ├─ main.py
│     ├─ api/
│     │  ├─ health.py
│     │  ├─ collections.py
│     │  ├─ articles.py
│     │  ├─ issues.py
│     │  ├─ briefings.py
│     │  ├─ settings.py
│     │  ├─ analysis.py
│     │  └─ exports.py
│     ├─ core/
│     │  ├─ config.py
│     │  ├─ paths.py
│     │  ├─ clock.py
│     │  └─ logging.py
│     ├─ domain/
│     │  ├─ article.py
│     │  ├─ observation.py
│     │  ├─ issue.py
│     │  ├─ cluster_run.py
│     │  ├─ briefing.py
│     │  ├─ briefing_version.py
│     │  ├─ assessment.py
│     │  └─ enums.py
│     ├─ repositories/
│     │  ├─ database.py
│     │  ├─ article_repository.py
│     │  ├─ observation_repository.py
│     │  ├─ issue_repository.py
│     │  ├─ cluster_run_repository.py
│     │  ├─ briefing_repository.py
│     │  ├─ briefing_version_repository.py
│     │  ├─ settings_repository.py
│     │  └─ run_repository.py
│     ├─ services/
│     │  ├─ collection/
│     │  │  ├─ collector.py
│     │  │  ├─ yonhap.py
│     │  │  ├─ google_news.py
│     │  │  └─ gdelt.py
│     │  ├─ extraction/
│     │  │  ├─ extractor.py
│     │  │  └─ cleaner.py
│     │  ├─ normalization/
│     │  │  ├─ title.py
│     │  │  ├─ url.py
│     │  │  ├─ source.py
│     │  │  └─ dates.py
│     │  ├─ deduplication/
│     │  │  ├─ exact.py
│     │  │  ├─ fuzzy.py
│     │  │  └─ service.py
│     │  ├─ classification/
│     │  │  ├─ rule_engine.py
│     │  │  └─ service.py
│     │  ├─ clustering/
│     │  │  ├─ features.py
│     │  │  ├─ proposal.py
│     │  │  └─ service.py
│     │  ├─ ai/
│     │  │  ├─ ollama_client.py
│     │  │  ├─ prompt_builder.py
│     │  │  ├─ schemas.py
│     │  │  └─ analyzer.py
│     │  ├─ briefing/
│     │  │  ├─ selection.py
│     │  │  ├─ rule_summary.py
│     │  │  └─ report_builder.py
│     │  └─ maintenance/
│     │     ├─ backup.py
│     │     └─ scheduler.py
│     └─ db/
│        ├─ migrator.py
│        └─ migrations/
│           └─ 0001_initial.sql
│
├─ config/
│  ├─ sources.yaml
│  ├─ search_rules.yaml
│  ├─ classification_rules.yaml
│  ├─ editorial_policy.yaml
│  └─ briefing_style_guide.md
│
├─ scripts/
│  ├─ import_localstorage_json.py
│  ├─ backup_database.py
│  └─ install_launchd.command
│
├─ data/
│  └─ kesco_media_briefing.db
├─ reports/
├─ backups/
├─ logs/
│
└─ tests/
   ├─ fixtures/
   │  ├─ rss/
   │  ├─ articles/
   │  └─ classification_cases.yaml
   ├─ unit/
   │  ├─ test_normalization.py
   │  ├─ test_deduplication.py
   │  ├─ test_classification.py
   │  ├─ test_clustering.py
   │  └─ test_ai_schema.py
   └─ integration/
      ├─ test_database_migrations.py
      ├─ test_collection_pipeline.py
      └─ test_api.py
```

---

## 6. 계층별 책임

### 6.1 Frontend

프런트엔드는 다음만 담당한다.

- API에서 받은 데이터 표시
- 필터·검색·정렬 같은 화면 상태
- 기사 선택, 중요 표시, 메모 입력
- AI 실행 요청과 진행상태 표시
- 담당자 직접 문장 수정
- 읽기 전용 보고 화면 표시
- 인쇄 호출

프런트엔드에 두지 않는 기능:

- RSS 호출
- 기사 URL 정규화
- 중복 제거
- 위험도 계산
- 관련도 계산
- 이슈 군집화
- SQLite 저장
- Ollama 직접 호출

### 6.2 API

API는 입력 검증과 서비스 호출만 담당한다. 업무 규칙을 route 함수에 직접 작성하지 않는다.

### 6.3 Domain

기사, 이슈, 브리핑, 평가의 데이터 구조와 불변조건을 정의한다. FastAPI나 SQLite 세부 구현에 의존하지 않는다.

### 6.4 Repository

SQLite 읽기·쓰기만 담당한다. 기사 수집이나 분류 판단을 하지 않는다.

### 6.5 Service

실제 업무 규칙을 담당한다.

- collection: 외부 수집원 호출
- extraction: 기사 본문 정제
- normalization: 제목·URL·매체·시각 표준화
- deduplication: 동일 기사 판정
- classification: 관련도·보도 성격·우선도 판정
- clustering: 같은 사건 기사 묶기
- ai: Ollama 분석과 응답 검증
- briefing: 선정 기사·이슈로 보고서 구성
- maintenance: 백업·예약 실행

---

## 7. 핵심 도메인 모델

### 7.1 Article

언론사가 게시한 보도 원본이다. 한 번 저장된 원본 사실과 수집 메타데이터는 담당자 편집 상태와 분리한다.

주요 필드:

```text
id
content_key
canonical_url
title
normalized_title
source
source_domain
published_at
first_observed_at
last_observed_at
description
body_text
body_status
body_fetched_at
body_error
category_hint
manual
publisher_id
publisher_allowed
created_at
updated_at
```

`content_key`는 다음 우선순위로 생성한다.

1. canonical URL hash
2. normalized title + source + published date hash

### 7.2 ArticleAssessment

기사 자동 판정과 담당자 최종 판정을 저장한다.

```text
article_id
auto_category
auto_event_type
auto_relevance_score
auto_severity_score
auto_priority_score
auto_priority
auto_tone
auto_reasons_json
final_category
final_event_type
final_priority
final_tone
manual_override
classifier_version
updated_at
```

화면 표시값은 `final_*`이 있으면 최종값, 없으면 `auto_*`를 사용한다.

### 7.2.1 KescoPressRelease와 ArticleOriginAssessment

공사 홍보센터 보도자료는 언론기사와 분리된 출처 대조 원문이다.

```text
kesco_press_releases
  id, bbs_seq, title, published_at, body_text, canonical_url, fetched_at

article_origin_assessments
  article_id, auto_origin_type, auto_press_release_id, confidence, reasons_json,
  final_origin_type, final_press_release_id, manual_override, classifier_version
```

`article_origin_assessments`는 관련도·심각도·보고 우선도를 담는 `ArticleAssessment`와 독립적이다.
자동 갱신은 `auto_*`만 바꾸며 담당자 `final_*`와 `manual_override`를 보존한다.

### 7.3 Issue

동일 사건·주제를 다룬 기사 묶음이다. 자동 군집 결과와 담당자 편집값을 분리한다.

```text
id
representative_article_id
auto_title
editor_title
auto_status
editor_status
auto_priority
editor_priority
first_seen_at
last_seen_at
direct_mention
needs_review
last_cluster_run_id
created_at
updated_at
```

유효 표시값은 `editor_*`가 있으면 담당자 값, 없으면 `auto_*`다.

상태:

```text
new        신규
ongoing    지속
expanding  확산
cooling    진정
closed     종료
```

기사 구성은 자동 membership과 담당자 add/remove override를 분리한다. 재군집화가 담당자 제목·상태·구성을 덮어쓰지 않는 상세 규칙은 `docs/API_DATA_CONTRACTS.md` 6장을 따른다.

AI 분석 근거 역할도 자동 대표와 담당자 확정값을 분리한다.

```text
issues
  representative_article_id                 자동 대표
  manual_representative_article_id          담당자 대표
  manual_supplemental_article_ids_json      담당자 보조근거(최대 2)
  manual_excluded_article_ids_json          담당자 분석 제외
  manual_selection_updated_at
  evidence_revision                         근거 구성 낙관적 잠금

article_extractions
  extraction_status, analysis_eligible
  content_quality_score, quality_grade
  quality_reasons_json, contamination_flags_json
  raw_character_count, cleaned_character_count
  complete_sentence_count, extraction_method, created_at
```

품질 점수는 LLM이 아니라 정제 결과, 본문/요약 상태, 문장 완전성, 출처·시각,
공식 도메인과 오염 플래그로 결정한다. MD 생성 경로에서만 확정 대표·보조근거 필터를
적용하며 Gemma 프롬프트, Ollama 호출과 AI 분석 응답 schema는 변경하지 않는다.
품질 점수는 관련기사 비교·정렬용이며 절대 오류를 상쇄하지 않는다. 본문 미확보·잘림,
정제 후 잔존 오염·언론사 AI 콘텐츠, 발행사 충돌, 실제 원문 URL 미확인은 점수 계산보다 먼저
`analysis_eligible=false`로 만든다. 성공적으로 제거된 페이지 부가 콘텐츠는 추적 사유로만
남긴다. 발행사는 페이지 메타데이터와 최종 URL 도메인으로 검증·정규화하며 provider 및 원래
`raw_source`와 분리한다.
관련기사 화면의 전체 재추출은 이슈 membership을 고정한 뒤 기사별 네트워크 추출을 동시에
수행하고, 완료된 결과를 추출 이력에 각각 추가한다. 대표기사 본문은 묶음을 펼치면 기본으로
표시하며 담당자는 본문 충실도 점수순으로 관련기사를 정렬해 근거를 비교한다.

브리핑 기사 카드의 `관련기사 검색`은 일반 일괄 수집과 분리된 사용자 요청 보강 경로다. 원
기사 제목에서 여러 개의 2~3단어 검색식을 만들고 Google 뉴스 RSS와 설정된 경우 네이버 뉴스
API를 90일 범위에서 조회한 뒤 중복을 제거해 최대 10건만 저장한다. 이 경로는 일반
수집의 검색그룹 관련도·제외어·24시간 gate와 신뢰 언론사 허용목록을 적용하지 않는다. 대신
검색 provider가 제공한 원 발행사 도메인이 없는 출처 미상 결과는 제외하고, MD의 실제 원문 URL·
발행사 일치·본문 품질 검증은 유지한다. 결과 observation은 별도 collection run에 남기고 현재
이슈에 수동 membership으로 연결하므로 이후 자동 재군집화가 담당자의 연결을 덮어쓰지 않는다.

MD 생성은 선택된 대표·보조근거 전체를 다시 검증하는 원자적 gate다. 오류가 하나라도 있으면
파일과 manifest를 만들지 않고 문제 기사·사유·이슈 ID를 반환한다. 프런트엔드는 해당 이슈의
관련기사 위치로 이동하거나 재추출할 수 있게 안내한다. 오류 기사를 자동 대체하거나 조용히
제외하지 않으며 담당자의 기존 선택도 보존한다.

Migration `0027_selected_evidence_validation.sql`은 추출 이력에 검증 필드를 추가한다. 적용 전
복구가 필요하면 운영 DB 자동 백업을 복원하고 migration 적용 전 앱 버전을 실행한다. 새 열은
기존 기사·관측·담당자 선택을 변경하지 않는다.

군집 검토순위는 동일 이슈라도 보고일 후보 집합에 따라 달라지므로 `issues`에 저장하지 않는다.

```text
issue_review_assessments
  briefing_id
  issue_id
  auto_score
  auto_rank
  auto_stars
  editor_stars
  editor_reason
  reasons_json
  scoring_version
```

자동 재계산은 `auto_*`와 근거만 갱신하며 담당자 `editor_stars`와 `editor_reason`을 보존한다.

### 7.4 Briefing

보고일별 **현재 작업본**이다. `report_date`당 정확히 1개만 존재한다.

```text
id
report_date
prepared_by
status
situation_summary
action_note
summary_mode
ai_model
ai_prompt_version
ai_generated_at
ai_input_signature
revision
latest_final_version
finalized_at
created_at
updated_at
```

`revision`은 API 낙관적 동시성 제어용이며, 최종 보고 version과 다르다.

상태:

```text
draft      작성 중
reviewed   검토 완료
final      최신 최종 snapshot과 동일하며 잠긴 상태
```

### 7.5 BriefingVersion

CEO에게 최종 보고한 불변 snapshot이다.

```text
id
briefing_id
version
source_revision
snapshot_json
report_html_path
finalized_at
created_at
```

- `(briefing_id, version)`은 UNIQUE다.
- 재확정할 때 기존 snapshot을 덮어쓰지 않고 version을 증가시킨다.
- `/report/{date}`는 가장 높은 최종 version을 선택한다.

### 7.6 BriefingArticle

기사 원본과 보고일별 편집 상태를 연결한다. 선택 해제해도 row와 메모를 보존한다.

```text
briefing_id
article_id
selected
starred
direct_coverage_override
note
dismissed
sort_order
created_at
updated_at
```

- 선택 해제: `selected=false`
- 목록 숨김: `dismissed=true`, 동시에 `selected=false`
- 기사 또는 군집 Top 태그 활성화: 해당 기사 `selected=true`; Top 해제 시 선정은 유지
- UI의 일반 동작에서 row를 DELETE하지 않는다.

### 7.7 BriefingIssue

이슈를 현재 작업본에 어떤 순서와 문구로 넣을지 저장한다.

```text
briefing_id
issue_id
selected
direct_coverage_override
sort_order
management_impact
action_required
editor_note
created_at
updated_at
```

단독 기사의 `공사 직접 보도` 자동값은 `effective_category == kesco_direct`이고,
군집 자동값은 `issues.direct_mention`이다. 보고일별 담당자 override는 각각
`briefing_articles.direct_coverage_override`, `briefing_issues.direct_coverage_override`에
저장하며 단독 기사 override는 최초 군집화 뒤에도 상속한다. 유효값이 참인 기사·군집은 일반 브리핑과
Top Issues에서 배타적으로 제외한다. `false` 수동 override도 명시적 담당자 판단이므로
재수집·재군집화로 덮어쓰지 않는다.

### 7.7.1 BriefingReportDraft

Gemma 실행 결과를 보존하면서 외부 AI 결과와 담당자 수정본을 CEO 보고에 적용하는
보고일별 편집 작업본이다.

```text
briefing_id
source_type          gemma | external | manual
source_label
content_json
evidence_json
input_signature
based_on_ai_run_id
created_at
updated_at
```

- 보고일별 작업본에 최대 1개를 둔다.
- `content_json`은 기존 AI 근거 ID schema와 동일하게 검증한다.
- 자동 AI 실행은 이 row를 생성하거나 덮어쓰지 않는다.
- 미리보기와 최종 snapshot은 이 값이 있으면 최신 정상 Gemma 결과보다 우선 사용한다.
- 기사·전문·편집 태그가 바뀌면 삭제하지 않고 stale로 표시한다.
- 외부 AI 일반 텍스트의 `오늘 한줄`, `언론 동향 분석`, `경영 참고사항`, `참고 동향` 제목과
  과거 `오늘의 핵심`, `경영 시사점` 제목은 기존 근거 schema의
  `managementMessage`, `situationSummary`, `urgency=reference`인 `keyIssues`로 정규화한다.
  과거 세 제목은 입력 호환 용도로만 인식한다.
- CEO 보고 화면은 이 세 분석 축을 본문으로 우선 표시하고 선정 기사는 제목·핵심 1줄·언론사
  중심의 붙임으로 표시한다.

### 7.8 CollectionRun

전체 수집 실행 요약이다.

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

### 7.9 CollectionRunProvider

provider 또는 provider+검색그룹별 실행 결과다.

```text
id
collection_run_id
provider
query_group_id
status
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

### 7.10 ArticleObservation

수집원이 반환한 개별 원본 관측이다. 동일 기사로 병합돼도 provider·수집 run 이력을 잃지 않는다.

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
dedup_method
dedup_score
```

`Article.source`는 발행 언론사이고 `ArticleObservation.provider`는 발견 경로다.

### 7.11 ClusterRun과 membership override

```text
cluster_runs
issue_auto_articles
issue_membership_overrides
```

재군집화는 proposal을 먼저 만들고 apply 단계에서 자동 필드만 갱신한다. 담당자 `editor_*` 값과 수동 add/remove는 유지한다.

### 7.12 AiRun

AI 분석의 재현성과 실패 추적을 위한 기록이다.

```text
id
briefing_id
model
prompt_version
input_signature
status
request_json
response_json
evidence_json
error_message
started_at
finished_at
```

`evidence_json`은 실행 당시 `A01 → article_id` 매핑을 보존한다.


## 8. SQLite 스키마 원칙

최소 테이블:

```text
schema_migrations
articles
article_observations
article_assessments
issues
issue_auto_articles
issue_membership_overrides
cluster_runs
briefings
briefing_versions
briefing_articles
briefing_issues
collection_runs
collection_run_providers
ai_runs
settings
```

필수 제약:

- `articles.content_key` UNIQUE
- `article_assessments.article_id` UNIQUE
- `briefings.report_date` UNIQUE
- `briefing_versions(briefing_id, version)` UNIQUE
- `briefing_articles(briefing_id, article_id)` UNIQUE
- `briefing_issues(briefing_id, issue_id)` UNIQUE
- `issue_auto_articles(issue_id, article_id, cluster_run_id)` UNIQUE
- `issue_membership_overrides(issue_id, article_id)` UNIQUE
- 모든 연결 테이블에 foreign key 적용
- SQLite 시작 시 `PRAGMA foreign_keys = ON`
- 운영 DB는 WAL 모드 사용
- migration 실행 전 자동 백업

업무 데이터 삭제 원칙:

- 기사 선택 해제는 `briefing_articles.selected=false`다.
- UI 휴지통은 `dismissed=true`이며 메모와 중요 표시를 보존한다.
- 수동 추가 기사 물리 삭제는 최종 snapshot이나 다른 브리핑에서 참조되지 않을 때만 허용한다.
- 최종 snapshot은 수정·삭제하지 않는다.
- API·삭제 조건의 상세 계약은 `docs/API_DATA_CONTRACTS.md` 1~3장을 따른다.

화면의 Media Coverage는 적용된 이슈 군집으로 기사를 묶어 표시한다. Top Issues는 자동 순위가
아니며 담당자가 군집 또는 개별 기사에 지정한 태그와 명시적으로 적용한 Gemma 핵심 추천을
합쳐 최대 6개 표시한다. 군집 태그는
`briefing_issues.selected`, 기사 태그는 `briefing_articles.top_issue`에 서로 독립적으로 저장한다.
Top Issues 카드는 자동 평가 통계보다 기사 유효 분류와 담당자 메모·검토 사유를 우선 표시하고,
군집과 개별 기사에 저장된 `sort_order`를 하나의 카드 배치 순서로 사용한다.
기사별 별도 `군집 선택` 체크박스로 2건 이상을 선택하면 수동 이슈를 생성할 수 있다. 수동
군집은 `issues.manual_group`과 `issue_membership_overrides`의 add/remove로 저장하며 자동
재군집화가 선택 기사를 다른 이슈에 중복 포함하지 않도록 적용 후 배타성을 복원한다.
수동 묶기 화면에서는 적용된 기존 이슈를 하나의 선택 단위로 표시하며, 선택 시 유효 구성원
전체를 새 수동 이슈로 이동하여 묶음끼리도 합칠 수 있다.


## 9. 설정 구조

### 9.1 파일과 DB의 역할

```text
config/*.yaml      버전 관리되는 기본 업무 규칙
.env               포트·경로·Ollama 주소 같은 기술 설정
settings 테이블    화면에서 변경한 사용자 override
```

시작 시 병합 순서:

```text
코드 기본값
→ config 파일
→ SQLite 사용자 override
```

“기본값 복원”은 사용자 override를 삭제하고 config 값으로 되돌린다.

### 9.2 설정 파일

- `sources.yaml`: 수집원 주소, 사용 여부, 우선순위, fallback 여부
- `collection_settings.json`: 검색 그룹·검색식·수집 상한·provider 사용 기본값
- `classification_rules.yaml`: 위험어, 예방 문맥, 예외 문구, 점수
- `editorial_policy.yaml`: 보고필수 기준, 최대 선정 건수, Top Issue 수
- `briefing_style_guide.md`: AI 문체, 금지사항, 근거 표기 규칙
- `trusted_media.yaml`: 일반 언론사 허용 도메인, 공식자료 예외, 승인된 중대사고 보조 언론

---

## 10. 기사 처리 파이프라인

```text
1. Collect
2. Parse
3. Normalize
4. Official/trusted source filter
5. Incident Sentinel and eligibility filter
6. Exact deduplication
7. Fuzzy duplicate detection
8. Classification
9. Issue clustering
10. Persist and return summary to UI
```

Incident Sentinel은 수집 보존과 사회적 심각성 추출을 담당하며 공사 관련도를 올리지 않는다.
화재 원인은 `cause_certainty`와 `cause_domain` 두 축으로 저장하고, 구체 원인 단서를 일반적인
“원인 조사 중” 문구보다 우선한다.

### 10.1 Collect

각 provider는 공통 인터페이스를 따른다.

```python
class NewsProvider(Protocol):
    async def collect(self, query, since, limit) -> list[RawArticle]: ...
```

수집원 하나가 실패해도 전체 실행을 실패시키지 않는다. 성공한 결과는 저장하고 실패한 provider를 `CollectionRun`에 기록한다.

### 10.2 Normalize

- HTML 제거
- 유니코드 NFKC 정규화
- 제목 뒤 매체명 제거
- 추적 query string 제거
- Google 뉴스 중계 URL과 원문 URL 구분
- Google RSS `<source url>`을 원문 발행 도메인 판별값으로 보존
- 매체명 표준화
- UTC 시각 저장

### 10.3 Exact deduplication

- canonical URL 동일
- content key 동일
- 표준 제목 완전 동일
- 동일 원문으로 확정되는 매우 높은 유사도

provider 응답은 먼저 `article_observations`에 기록한다. 완전 중복은 하나의 `articles` row로 연결하되 각 observation과 collection run 이력은 보존한다.

일반 언론기사는 `trusted_media.yaml`의 도메인 허용목록을 먼저 통과해야 한다. 공식자료
도메인은 별도 예외로 허용하고, 허용·제외·출처 미상 건수는 collection run에 JSON으로
저장한다. Google 뉴스 RSS는 `news.google.com` 중계 URL을 판별에 사용하지 않는다.

### 10.4 Fuzzy duplicate detection

완전 중복과 동일 이슈 군집화를 구분한다.

- 동일 원문의 재게시·중계: 하나의 Article + 여러 observation
- 같은 사건을 별도 취재·작성: 별도 Article + 같은 Issue

초기 방식:

- 한국어 문자 n-gram 제목 유사도
- 보도시각 차이
- 핵심 숫자·지역·기관 문자열 겹침
- 판정 방법과 score를 observation에 기록

### 10.4.1 공사 보도자료 출처 판정

전용 갱신 API와 서버 시작 백그라운드 작업이 `kesco.or.kr/pr`의 보도자료 목록과 상세 본문을
기준 원문으로 저장한다. 이 자료는 NewsProvider 결과나 브리핑 후보 기사로 넣지 않는다.
담당자는 별도 조회 화면에서 저장된 제목·게시일·본문과 공식 원문 링크를 직접 확인할 수 있다.
일반 기사 수집은 외부 공사 사이트를 다시 호출하지 않고 저장 원문만 읽는다. 기사 정규화·분류 직후, 군집화 전에
제목 문자 n-gram, 핵심어 겹침, 발행일 범위를 규칙 기반으로 비교해 `kesco_republication`과
`kesco_based`를 판정한다. 보도자료 갱신 실패는 서버 기동이나 일반 provider 수집 결과에 영향을
주지 않으며 마지막 정상 원문을 계속 사용한다.

동일 날짜에 발행된 기사가 보도자료 제목을 크게 재작성한 경우에도, 제목 유사도와 기사 요약·
보도자료 본문의 다수 핵심어 중첩을 함께 확인해 `kesco_based`로 판정한다. 자동 추천 입력을 만들
때는 아직 저장 판정이 없는 기사에도 저장된 보도자료 원문으로 같은 판정을 적용해 누락을 막는다.

### 10.5 Classification

서로 다른 축을 분리한다.

```text
관련도 점수: relevance_score 0~100
심각도 점수: severity_score 0~100(군집 검토점수의 내부 근거)
군집 검토점수: review_score 0~100
군집 검토별점: 1~5, 보고일별 상위 10·20·40·100위와 점수 하한 병용
보도 성격: accident / prevention / management_risk / policy / achievement / community / general / mixed
레거시 보고 우선도: required / review / reference(과거 데이터 호환 전용)
```

신규 화면·정렬·최종 보고는 군집 검토별점을 사용한다. 관련도 30%, 경영영향도 25%,
보도확산도 20%, 긴급성 15%, 대응적합도 10%의 산식과 순위·점수 하한은
`docs/API_DATA_CONTRACTS.md` 4장을 따른다. 기사 심각도와 레거시 우선도는 자동 근거와
과거 백업 호환을 위해 보존하지만 위험 신호로 표시하지 않는다.

필수 예외 fixture:

```text
전기화재 예방 캠페인   → prevention / reference
감전 예방 교육         → prevention / reference
화재로 인명피해        → accident / required 또는 review
감사패 전달            → achievement / reference
감사원 감사 결과       → management_risk / review 또는 required
정전 예방 특별점검     → prevention / reference
대규모 정전 발생       → accident / required 또는 review
```

### 10.6 Issue clustering

1차 구현은 외부 임베딩 서버 없이 동작해야 한다.

- 제목+요약 문자 n-gram TF-IDF
- 최근 72시간 후보만 비교
- 시간 차이 가중치
- 공통 지역·기관·사고 유형 가중치
- 일정 threshold 이상이면 기존 open issue 후보로 제안
- 같은 공사 보도자료 ID에 연결된 기사 쌍은 출처 원문을 강한 군집 anchor로 사용한다.

재군집화는 `cluster_run` proposal과 apply 두 단계로 처리한다. `editor_title`, `editor_status`, `editor_priority`, 수동 add/remove membership은 자동 결과로 덮어쓰지 않는다. 상세 계약은 `docs/API_DATA_CONTRACTS.md` 6장을 따른다.


## 11. API 계약

응답 공통 형태:

```json
{
  "ok": true,
  "data": {},
  "error": null,
  "meta": {
    "revision": 12
  }
}
```

오류 응답:

```json
{
  "ok": false,
  "data": null,
  "error": {
    "code": "BRIEFING_REVISION_CONFLICT",
    "message": "다른 화면에서 브리핑이 변경됐습니다.",
    "details": {}
  }
}
```

상세 선택·삭제·근거·재군집화 계약은 `docs/API_DATA_CONTRACTS.md`가 우선한다.

### 11.1 상태

```text
GET /api/health
```

반환:

- app 상태
- DB 연결
- Ollama 연결
- 사용 가능 모델
- 앱 버전
- 마지막 정상 수집 시각

### 11.2 설정

```text
GET  /api/settings
PUT  /api/settings
POST /api/settings/reset
```

### 11.3 수집

```text
POST /api/collections
GET  /api/collections/latest?report_date=YYYY-MM-DD
GET  /api/collections/{collection_run_id}
```

반환에는 전체 status(`success|partial|failed`), provider별 성공·실패, stale 재사용 수,
중복 통계와 `source_filter_stats`를 포함한다.

### 11.4 기사

```text
GET    /api/articles?report_date=YYYY-MM-DD&include_dismissed=false
POST   /api/articles
PATCH  /api/articles/{article_id}/assessment
PATCH  /api/briefings/{date}/articles/{article_id}
DELETE /api/articles/{article_id}?confirm=true
```

- 선택 해제와 UI 휴지통은 PATCH다.
- `DELETE /api/briefings/{date}/articles/{article_id}`는 두지 않는다.
- 물리 삭제는 미참조 수동 기사만 허용한다.

### 11.5 이슈·재군집화

```text
GET   /api/issues?report_date=YYYY-MM-DD
PATCH /api/issues/{issue_id}
PATCH /api/briefings/{date}/issues/{issue_id}
POST  /api/cluster-runs
GET   /api/cluster-runs/{cluster_run_id}
POST  /api/cluster-runs/{cluster_run_id}/apply
```

재군집화 첫 요청은 `0.15~0.70` 범위의 선택적 `similarityThreshold`(기본 `0.40`)로 diff proposal을 만들고, apply 시 자동 필드만 갱신한다. 브라우저는 기사량이 많은 작업본도 계산을 기다릴 수 있도록 제안 생성 요청에 120초 제한을 적용한다. 화면에서 기준을 바꾼 경우 새 proposal을 계산하기 전에는 이전 proposal을 적용할 수 없다.

수동 `오늘 기사 검색`과 화면 진입 시의 당일 자동 검색은 수집 성공 후 `0.15` 기준 cluster
proposal을 생성하고 즉시 apply한다. 화면 진행률은 수집 요청, 기사 목록 갱신, proposal 계산,
apply 완료라는 실제 경계에서 갱신한다. 재군집화 실패는 수집된 기사를 롤백하지 않는다.

### 11.6 브리핑 작업본·최종본

```text
GET  /api/briefings
GET  /api/briefings/{date}
PUT  /api/briefings/{date}
GET  /api/briefings/{date}/versions
GET  /api/briefings/{date}/versions/{version}
POST /api/briefings/{date}/rule-summary
POST /api/briefings/{date}/analyze
POST /api/briefings/{date}/finalize
POST /api/briefings/{date}/reopen
```

- `/api/briefings`는 과거 작업본과 최종 version 존재 여부를 찾기 위한 보고일 내림차순 목록이다.
- 날짜 조회는 해당 날짜의 유일한 작업본을 반환한다.
- 모든 mutation은 `expectedRevision`을 요구한다.
- final 상태에서는 일반 수정이 거부된다.

### 11.7 보고·내보내기

```text
GET /preview/{date}
GET /report/{date}
GET /report/{date}?version=N
GET /api/exports/{date}.json?scope=working|latest-final|version:N
GET /api/exports/{date}.csv?scope=working|latest-final|version:N
POST /api/exports/{date}.md
GET /api/briefings/{date}/report-draft
POST /api/briefings/{date}/report-draft/validate
PUT /api/briefings/{date}/report-draft
```

- `/preview/{date}`는 현재 작업본이다.
- `/report/{date}`는 최신 최종 snapshot만 제공하며 최종본이 없으면 404다.
- JSON은 정식 백업, CSV는 손실형 목록 교환 포맷이다.
- Markdown은 선정 기사 전문·태그와 고정 근거 ID를 외부 AI에 전달하는 분석 교환 포맷이다.
- 외부 AI 결과는 검증 후 별도 CEO 보고 편집본으로 저장하며 Gemma 실행 이력을 덮어쓰지 않는다.


## 12. 프런트엔드 상태 설계

프런트엔드 상태를 두 종류로 나눈다.

### 서버 상태

- 현재 보고일 브리핑
- 기사 목록
- 이슈 목록
- 설정
- 수집 실행 결과
- AI 분석 결과

API에서 다시 불러올 수 있는 값이다.

### UI 상태

- 검색어
- 필터
- 정렬
- 열린 modal
- loading 상태
- toast

브라우저 새로고침 시 사라져도 되는 값이다.

`localStorage`는 다음 용도로만 제한한다.

- 마지막 선택한 화면 필터
- 사용자가 닫은 안내 여부

업무 데이터는 저장하지 않는다.

---

## 13. AI 분석 구조

### 13.1 처리 범위

AI는 담당자가 선정한 기사 또는 이슈만 분석한다. 기본 상한은 20건이다.

분석 시작 시 선정 기사(상한 20건)의 전문을 병렬 수집한다. 확보한 전문은 `articles.body_text`에
저장해 다음 실행에서 재사용한다. 언론사 차단·유료벽·본문 식별 실패는 `body_error`에 기록하고
기존 RSS 요약으로 폴백한다. 전문 수집 실패가 전체 AI 분석 실패로 위장되거나 기존 요약을
삭제해서는 안 된다. 내부망 URL은 수집하지 않으며 리다이렉트된 주소도 같은 검증을 적용한다.

AI 분석은 단일 Mac의 GPU 과점유를 막기 위해 앱 전체에서 한 번에 하나만 실행한다. 프런트의 취소 버튼, 브라우저 연결 종료, 경영메시지와 기사 추천의 20분 총 제한은 모두 같은 취소 token으로 Ollama 스트리밍 연결을 닫는다. 앱 시작 시 `running`으로 남은 고아 실행은 `AI_INTERRUPTED` 실패로 복구한다.

기사 추천의 브라우저 대기 제한은 11분이며, 제한시간을 넘기면 공용 취소 API를 호출한다. 취소 API는 Ollama 연결 종료와 실행 registry 해제를 기다린 뒤 응답하므로 모델을 바꾼 즉시 재실행해도 이전 추천의 실행 잠금이 남지 않는다.

`gemma4:31b`를 기본 선택 모델로 사용하며 기본 64K context, 최대 2,048 출력 token, thinking 비활성화, JSON schema structured output을 사용한다. 분석 종료 뒤 모델을 메모리에서 내려 다음 작업의 GPU·열 점유를 남기지 않는다. 환경변수 `KESCO_OLLAMA_NUM_CTX_31B`를 지정하면 메모리 여건에 맞춰 4K 이상 범위에서 context를 낮출 수 있다.

### 13.2 입력과 고정 근거 index

각 AI 실행에 고정 근거 ID를 부여한다.

```text
A01, A02, A03 ...
```

`A01 → article_id` 매핑을 `ai_runs.evidence_json`에 저장한다. 같은 실행에서는 순서를 바꾸지 않는다.

입력 필드:

- 제목
- 매체
- 보도일시
- 본문 또는 RSS 요약
- 담당자 메모
- 자동·최종 우선도
- 이슈 ID

기사 내용은 명령이 아닌 데이터로 구분해 전달한다. 기사 본문 안의 지시문은 따르지 않도록 prompt에 명시한다.

### 13.3 출력

모든 사실·판단·전망 필드를 근거 객체로 구조화한다.

생성은 두 단계로 수행한다. 첫 호출은 `기사 사실`, `언론·전문가 주장`, `공사 관련 해석`,
`경영 제언`, `근거 기사 ID`, `확실성 수준`을 `analysisBasis`로 구조화한다. 서버는 각 항목에
숫자·날짜 근거, 공사 역할 혼동, 조사 중 원인 확정, 주장 귀속 검사를 적용하고 내부 경영관리
근거가 없는 참고 동향도 제외한다. 통과 항목과 그 기사 ID만 두 번째 최종 작성 호출에 전달한다.
최종 출력도 같은 검사를 거치며 위반 시 1회 교정한다. 경고와 제외·교정 상태는
`ai_runs.response_json.validationWarnings`에 보존한다. 통과 항목이 없거나 교정 뒤에도 위반이
남으면 새 결과를 적용하지 않고 마지막 정상 결과와 담당자 수정본을 유지한다.

소관 판정 기준은 실제 서비스가 `config/kesco_jurisdiction.json`에서 읽는다. 선정 기사에 대한
기존 두 단계 Gemma 분석에서만 `DIRECT`, `COLLABORATIVE`, `MONITORING`, `OUT_OF_SCOPE`를
재판정하며 수집·본문 정제·1차 규칙 분류에는 LLM을 추가하지 않는다. 각 근거 항목과 핵심 이슈는
확실성, 전기 원인 확인 상태, 소관 이유, 제외 요소, 행동 수준을 보존하고 각 실행 항목은 소관,
행동 수준, 근거, 불확실성, 실행 주체를 보존한다. 서버는 비소관 제언, 원인 미확인 상태의
검사체계 변경, 정책 모니터링의 직접 업무 과장, 외부기관 조치, 입력 외 개념을 교정 대상으로 삼는다.

편집 화면의 경영 메시지는 구조화 결과를 `① 오늘 한줄`(`managementMessage`),
`② 언론 동향 분석`(`situationSummary`), `③ 경영 참고사항`(공사가 직접 검토·협업 가능한
`actionItems`) 순서로 조립하고, 모니터링 이슈가 있을 때만 `④ 참고 동향`을 추가한다.
참고 동향은 공사의 즉시 안전대응 핵심과 분리할 정책·산업 흐름이며, 근거가 없을 때 모델이
억지로 생성하지 않는다. 나머지 구조화 필드는
CEO 보고 미리보기와 근거 검증을 위해 그대로 보존한다.

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

### 13.4 검증

- Pydantic schema 검증
- 내용이 있는 모든 주장 필드에 1개 이상의 근거 ID 필수
- 존재하지 않는 ID가 하나라도 있으면 결과 전체 적용 금지
- `riskOutlook.isInference=true` 필수
- `limitations`만 빈 근거 배열 허용
- JSON·근거 검증 실패 시 형식교정 재시도 최대 1회
- 기사에 없는 수치·기관·발언 생성 금지
- 본문 미확보 건수와 분석 한계 표시

### 13.5 수동 수정 보존

AI 생성 직후 `summary_mode = ai`다. 담당자가 수정하면 `ai-edited`로 바뀐다.

기사 선택, 메모, 모델이 바뀌면 기존 분석은 삭제하지 않고 `stale`로 표시한다. 재생성은 담당자가 직접 실행한다. 검증 실패 시 기존 결과와 수동 수정본을 유지한다.


## 14. 보고 화면

### 14.1 편집 화면 `/`

- 수집 상태
- 기사·이슈 필터
- 선정·중요 표시·메모
- 자동 판정 수정
- AI 분석
- 종합상황 직접 편집
- CEO 참고·지시사항

### 14.2 CEO 보고 화면 `/report/{date}`

편집 컨트롤을 전혀 포함하지 않는다.

권장 순서:

1. 보고일과 작성자
2. 오늘의 언론상황
3. 핵심 이슈 최대 3건
4. 이슈별 공사 영향
5. 확인·지시 필요사항
6. 공사 직접 보도
7. 선정 기사 별첨

### 14.3 최종 확정

최종 확정 시 다음을 수행한다.

- 작업본의 `expectedRevision`을 검증한다.
- `briefing_versions`에 version N의 불변 JSON snapshot을 추가한다.
- `reports/YYYY/MM/`에 같은 version의 읽기 전용 HTML을 저장한다.
- 작업본 상태를 `final`로 잠근다.
- DB 백업을 실행한다.

수정이 필요하면 `reopen`으로 작업본을 다시 열고, 기존 version은 보존한다. 재확정 시 N+1 snapshot을 만든다. `/report/{date}`는 최신 최종 version을, `/preview/{date}`는 현재 작업본을 사용한다.

---

## 15. 장애·복구 설계

### 수집 실패

- 기존 기사 유지
- 실패한 provider만 표시
- 마지막 정상 수집 시각 표시
- 동일 provider 즉시 반복호출 제한

### Ollama 실패

- AI 버튼 비활성 또는 오류 표시
- 기존 AI 결과와 담당자 수정본 유지
- 기본 규칙 요약은 계속 사용 가능

### DB 오류

- 쓰기 실패 시 사용자에게 명확히 표시
- 앱 시작 시 DB integrity check
- migration 전 백업
- 최근 정상 backup 선택 복구 스크립트 제공

앱 시작 전 기존 DB에 `PRAGMA integrity_check`를 수행한다. DB 백업은 파일 복사가 아니라
SQLite online backup API를 사용해 WAL의 커밋 내용까지 단일 파일로 보존하고, 생성 직후
다시 무결성을 검사한다. 복구는 서버 정지 상태에서만 수행하며 현재 DB 안전 백업 → 선택
백업 검증 → 임시 DB 복제·검증 → 원자 교체 순서를 따른다.

### 앱 중복 실행

`start_kesco_briefing.command`는 8787 포트를 확인한다.

- 이미 정상 서버가 있으면 새 서버를 띄우지 않고 브라우저만 연다.
- 비정상 프로세스가 포트를 점유하면 로그 위치와 조치 방법을 표시한다.

포트 확인과 별도로 `data/server.lock`에 `flock` 단일 인스턴스 잠금을 둔다. health의
`service=kesco-media-briefing`이 일치할 때만 기존 정상 서버로 인정한다.

---

## 16. 실행·배포 구조

### 최초 1회

```text
setup_kesco_briefing.command
```

역할:

- Python 확인
- `.venv` 생성
- 의존성 설치
- DB migration
- 필수 디렉터리 생성
- 실행권한 설정

### 매일 실행

```text
start_kesco_briefing.command
```

역할:

1. 기존 서버 확인
2. Ollama 상태 확인
3. FastAPI 실행
4. health 확인
5. 기본 브라우저에서 화면 열기
6. 로그 기록

의존성 설치나 migration을 매일 무조건 반복하지 않는다.

### 자동 수집

기능 안정화 후에만 `launchd`를 추가한다. 자동수집이 실패해도 수동 `오늘 기사 검색`은 유지한다.

Phase 9 기본값은 로그인 시 서버 자동 시작과 2시간 간격 수집이다. 검색 기본값은
`config/collection_settings.json`, 담당자 변경은 SQLite `settings` override에 둔다. 화면과
자동수집 스크립트는 검색식을 요청 바디에 복제하지 않고 같은 서버 유효 설정을 사용한다.
자동·수동 수집이 겹치면 두 번째 요청은 `COLLECTION_ALREADY_RUNNING`으로 거부하고 기존 실행을 유지한다.

---

## 17. 로그·백업

### 로그

```text
logs/app.log
logs/collection.log
logs/ai.log
```

운영 로그에는 API key나 전체 기사 원문을 남기지 않는다. 단, 이 프로젝트는 외부 보안보다는 오류 추적과 저장공간 관리가 목적이다.

### 백업

```text
backups/db/YYYY-MM-DD_HHMMSS.db
backups/briefing/YYYY-MM-DD_vN.json
reports/YYYY/MM/KESCO_일일언론브리핑_YYYY-MM-DD_vN.html
```

보존 기본값:

- DB 자동백업: 최근 30개
- 최종 브리핑 snapshot: 삭제하지 않음
- 로그: 크기 기반 회전

구현 기본값은 DB 최근 30개, 로그 파일당 5 MiB와 과거 파일 5개다. 현재 정식 백업은
schemaVersion 12이며 기사 전문·전문 수집 상태, 사고 Sentinel, 원인 확정 수준·분야,
공사 직접 보도 수동 override를 왕복한다. 최종 확정 시 JSON을
`backups/briefing/YYYY-MM-DD_vN.json`에도 저장하며 최종 snapshot과
HTML은 자동 삭제하지 않는다. 운영 상태는 `GET /api/operations/status`에서 DB 무결성,
최근 백업, 마지막 수집과 마지막 정상 수집을 함께 확인한다.

설정 화면의 서버 재시작은 확인 헤더가 필요한 `POST /api/operations/restart`로 요청한다.
응답 후 별도 로컬 도우미가 현재 프로세스가 launchd 관리 대상인지 판별해 launchd job을
재시작하거나, 수동 실행 프로세스가 종료된 뒤 `scripts/run_server.py`를 다시 실행한다.
브라우저는 새 health `instanceId`를 확인한 뒤 화면을 자동으로 새로고침한다.

---

## 18. 테스트 전략

### 단위 테스트

- URL·제목·날짜 정규화
- provider observation 보존
- 완전·유사 중복 판정
- 부분 provider 실패 시 기존 후보 보존
- 예방/사고 문맥 구분
- 감사/감사패 구분
- 관련도·심각도 점수 breakdown과 required/review 임계값
- hard floor·cap 충돌 순서
- 브리핑 최종값 우선 규칙
- 선택 해제 후 메모·중요 표시 보존
- 이슈 재군집화 후 editor override 보존
- AI JSON schema와 모든 근거 ID 검증

### 통합 테스트

- fixture RSS → observation → article 저장 전체 파이프라인
- provider 일부 실패 → `partial` run → stale 기존 기사 유지
- SQLite migration
- 보고일별 단일 작업본과 revision conflict
- finalize → version 1 → reopen → version 2
- JSON export/import 의미상 왕복
- CSV 손실형 import 경고와 formula escape
- AI fake client의 잘못된 A99 근거 거부
- cluster proposal/apply와 수동 membership override
- 최종 report HTML이 snapshot으로 재생성됨

### 수동 회귀 테스트

Phase 0·1은 `docs/MANUAL_REGRESSION_CHECKLIST.md`를 사용한다. 현행 로직 위험은 `docs/KNOWN_RISKS.md`에 기록하고 Phase 1에서 임의 수정하지 않는다.

### 외부 연결 테스트

기본 테스트에서는 실제 뉴스 사이트와 Ollama를 호출하지 않는다. 별도 `manual` 또는 `live` 표식이 있는 테스트로 분리한다.

### 필수 한국어 분류 fixture

```text
전기화재 예방 캠페인 확대
감전 예방 교육 실시
공장 전기화재로 2명 사상
감사패 전달
감사패 전달 뒤 감사원 감사 착수
감사원 감사 결과 발표
정전 예방 특별점검
대규모 정전 발생
전기안전공사 관련 허위정보 확산
```


## 19. 단계별 구현 순서

### Phase 0. 기준선 고정

- `.gitignore` 적용 및 `.DS_Store` 제거
- 원본 HTML 보관·실행 확인
- `docs/MANUAL_REGRESSION_CHECKLIST.md` 수행
- `docs/KNOWN_RISKS.md` 기준 위험 등록
- Git 최초 커밋

완료 기준: 원본을 언제든 실행할 수 있고, 의도한 파일만 추적되며, 수동 회귀 기준이 기록돼 있다.

### Phase 1. 프런트엔드 파일 분리

- CSS 분리
- JavaScript ES Module 분리
- 화면·기능 변경 금지

완료 기준: 원본과 기능이 동일하다.

### Phase 2. FastAPI 골격

- 정적 파일 제공
- `/api/health`
- 원클릭 실행
- 로그

완료 기준: `.command` 실행으로 화면과 health가 열린다.

### Phase 3. 수집 백엔드 이전

- RSS/GDELT 호출을 Python으로 이동
- 프런트엔드 공개 CORS proxy 제거
- `collection_runs`, `collection_run_providers`, `article_observations` 도입
- provider 일부 실패 시 기존 후보 보존

완료 기준: 브라우저에 수집 business logic이 남지 않고, 부분 실패가 기존 자동 기사를 제거하지 않으며 provider별 이력을 조회할 수 있다.

### Phase 4. SQLite 이전

- DB migration
- 보고일별 단일 작업본·revision·최종 snapshot 도입
- 기사 선택/숨김 상태를 PATCH로 저장
- 기존 JSON import와 versioned JSON round-trip
- CSV를 손실형 교환 포맷으로 명시

완료 기준: 브라우저 저장소를 지워도 업무 데이터가 보존되고, 선택 해제 후 메모·중요 표시가 유지되며 JSON 백업이 왕복 복원된다.

### Phase 5. 판정 로직 재구축

- ArticleAssessment
- 관련도·심각도·우선도 점수 분리
- required/review 임계값과 hard floor·cap
- 예방·사고·감사 문맥 충돌 순서
- 자동값/최종값 분리
- fixture 테스트

완료 기준: 점수 breakdown과 적용 rule을 설명할 수 있고 대표 오분류 테스트를 모두 통과한다.

### Phase 6. 이슈 군집화

- 기사와 Issue 분리
- cluster run proposal/apply
- 자동 필드와 editor override 분리
- 수동 add/remove membership 보존
- 신규·지속·확산 계산

완료 기준: 동일 사건 기사 여러 건을 원본 보존 상태로 볼 수 있고 재군집화가 담당자 제목·상태·구성을 덮어쓰지 않는다.

### Phase 7. AI 분석 안정화

- Ollama client 단일화
- 모든 주장 필드의 구조화 근거 schema
- decisionPoints·riskOutlook 포함 전체 근거 검증
- 존재하지 않는 ID 거부와 1회 교정 재시도
- stale 판정

완료 기준: 잘못된 근거 ID가 하나라도 있는 결과는 적용되지 않고 수동 수정이 보존된다.

### Phase 8. CEO 보고 분리

- 읽기 전용 report route
- 최종확정·version·snapshot
- 인쇄 품질 조정

완료 기준: 편집 화면과 무관하게 동일 데이터로 재생성할 수 있다.

### Phase 9. 자동화·운영 안정화

- 백업
- `launchd`
- 장애 복구
- 실사용 병행 테스트

완료 기준: 1~2주 병행운영에서 데이터 손실과 중대한 누락이 없다.

---

## 20. 아키텍처 결정 기록

### ADR-001: 프런트엔드 프레임워크를 사용하지 않는다

로컬 단독 업무도구이고 기존 HTML 자산이 충분하다. 빌드 시스템과 Node 의존성을 추가할 실익이 현재는 낮다.

### ADR-002: FastAPI를 로컬 애플리케이션 경계로 사용한다

브라우저 CORS 문제를 없애고 수집·SQLite·Ollama를 한 프로세스에서 관리한다.

### ADR-003: SQLite와 repository 계층을 사용한다

단일 사용자·단일 Mac 환경에 적합하고 별도 DB 서버가 필요 없다. 업무 규칙은 SQL과 분리한다.

### ADR-004: 기사·이슈·브리핑을 별도 모델로 둔다

중복 기사와 동일 이슈를 구분하고, 날짜별 선정 상태가 원본 기사를 오염시키지 않게 한다.

### ADR-005: 규칙 파일은 Git, 사용자 수정은 DB override로 관리한다

기본 규칙의 변경이력을 보존하면서 화면 편집도 가능하게 한다.

### ADR-006: AI는 구조화 결과와 근거 ID를 필수로 한다

문체 품질보다 재현성·검증 가능성을 우선한다.

### ADR-007: 최종 보고는 읽기 전용 HTML snapshot으로 남긴다

브라우저 UI 변경 이후에도 과거 보고를 동일하게 열 수 있게 한다.

### ADR-008: 보고일별 작업본은 하나이고 최종 version은 snapshot으로 분리한다

날짜 기반 API의 version 선택 모호성을 없애고 편집 revision과 최종 보고 version을 분리한다.

### ADR-009: 기사 선택 해제는 DELETE가 아니다

선택 상태 변경으로 메모·중요 표시가 사라지지 않게 `briefing_articles` row를 보존한다.

### ADR-010: provider 응답은 observation으로 보존한다

완전 중복을 하나의 기사로 병합해도 어느 수집 run과 provider에서 발견됐는지 추적한다.

### ADR-011: 재군집화는 proposal/apply이며 editor override를 덮지 않는다

자동 군집 품질을 개선해도 담당자의 제목·상태·구성 편집은 우선한다.

---

## 21. 기사 근거 정제와 AI 입력 Markdown

Gemma 분석 호출과 독립된 서버 파이프라인이 선정 기사 근거를 준비한다.

```text
선정 기사 snapshot
→ 원문/JSON-LD/언론사 DOM/모바일·AMP·인쇄 재시도
→ 원본과 정제본 분리 저장
→ 적격성·언론사 품질 gate
→ 확정 군집 우선 대체기사 연결
→ 기사별/문서별 예산
→ 검토 완료 기상정보 결합
→ SHA-256 서명
→ 원자적 Markdown 저장
```

- `services/extraction`은 네트워크·DOM 추출까지만 담당하며 문장을 요약하거나 재작성하지 않는다.
- 결정론적 본문 정제기는 독립된 페이지 UI 줄, `사진=...` 형식의 사진 캡션과
  `재판매 및 DB 금지` 꼬리표만 제거한다. 해당 낱말이 포함된 일반 기사 문장은 보존한다.
- `services/analysis_markdown`은 정제, 적격성, 대체, 품질 통계, 예산, 빌드, 서명, 저장을 담당한다.
- `articles.body_text`는 기존 원문 호환 필드로 유지한다. 실행별 `raw_text`, `cleaned_text`, 시도와
  실패 사유는 `article_extractions`에 추가 기록한다.
- 언론사 품질 표본이 10건 미만이면 자동 차단하지 않고 `warning`으로 둔다. 충분한 표본에서
  적격 성공률이 기준 미달인 `quarantine`과 설정상 `disabled`만 AI 입력에서 제외한다.
- 이 파이프라인은 Ollama를 호출하지 않으며 `/api/analyze`와 AI JSON schema를 변경하지 않는다.
- 생성 완료 manifest(`briefing_analysis_markdown`)는 MD의 입력 서명과 실제 `Axx` 근거표를
  CEO 보고 편집본 검증에 연결한다. 원문·선정·태그·검토 기상·설정 입력이 달라지면 manifest를
  사용하지 않으므로 과거 MD 결과를 현재 작업본에 저장할 수 없다.

### migration 0023·0024·0025 복구

변경은 기존 테이블/컬럼을 수정하지 않는 additive migration이다. 장애 시 우선 작업 전 DB
백업을 복원한다. 빈 이력만 되돌리는 경우 서버를 중지하고 `briefing_analysis_markdown`,
`publisher_extraction_events`, `article_extractions` 순으로 drop한 뒤 `schema_migrations`의
`0025_analysis_markdown_manifest.sql`, `0024_publisher_quality_rule_version.sql`,
`0023_analysis_markdown_pipeline.sql` row를 역순으로
제거할 수 있다. SQLite에서는 0024의 단일 컬럼만 별도로 제거하기보다 두 이력 테이블을 함께
복구 대상으로 삼는다. 기사·브리핑 원본은 두 테이블과 외래키 방향상 영향을 받지 않는다.

## 22. 구현 시 금지할 과잉 설계

- 초기부터 마이크로서비스로 분리
- Redis, Celery, PostgreSQL 도입
- Docker 필수화
- 외부 인증
- 이벤트 버스
- 복잡한 CQRS
- 모든 기사에 LLM 분류 실행
- 최초 단계에서 임베딩 DB 도입
- 단일 사용자 도구에 다중조직 권한 모델 추가
- 기존 HTML을 React로 전면 재작성

---

## 23. 첫 Codex 작업 지시

```text
현재 저장소의 `legacy/kesco_media_briefing_original.html`을 회귀 기준으로 삼아라.

Phase 1 전에 Phase 0을 완료한다.
1. `.gitignore`를 적용하고 모든 `.DS_Store`를 삭제한다.
2. `docs/MANUAL_REGRESSION_CHECKLIST.md`로 원본을 수동 검증한다.
3. `docs/KNOWN_RISKS.md`의 기존 위험을 Phase 1에서 임의로 수정하지 않는다.
4. 의도한 파일만 포함해 최초 Git commit을 만든다.

그 다음 작업 범위는 Phase 1만이다.
1. 화면 디자인과 기능을 변경하지 않는다.
2. 인라인 CSS를 `frontend/css`로 분리한다.
3. 인라인 JavaScript를 ES Module로 분리한다.
4. 아직 RSS 수집, localStorage, AI 호출 로직은 동작 위치를 바꾸지 않는다.
5. 원본과 분리본을 수동 체크리스트로 비교한다.
6. 신규 프레임워크와 신규 기능을 추가하지 않는다.
7. 완료 후 수정 파일, 함수 이동표, 테스트 결과, 남은 위험을 보고한다.
```
