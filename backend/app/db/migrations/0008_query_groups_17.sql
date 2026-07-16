-- 기사 수집 설계 변경 단계 2: Sentinel 사고 정보를 단일 JSON 컬럼에 보존한다.
-- 신뢰 언론사 컬럼은 단계 3 migration으로 분리한다.
ALTER TABLE article_assessments ADD COLUMN incident_json TEXT;
