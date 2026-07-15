-- Phase 5: 자동 판정 축과 담당자 최종값을 분리한다.
-- Phase 4 호환 컬럼(auto_risk 등)은 기존 JSON/CSV와 화면의 점진 전환을 위해 보존한다.

ALTER TABLE article_assessments ADD COLUMN auto_event_type TEXT;
ALTER TABLE article_assessments ADD COLUMN auto_relevance_score INTEGER;
ALTER TABLE article_assessments ADD COLUMN auto_severity_score INTEGER;
ALTER TABLE article_assessments ADD COLUMN auto_priority_score INTEGER;
ALTER TABLE article_assessments ADD COLUMN auto_priority TEXT;
ALTER TABLE article_assessments ADD COLUMN auto_tone TEXT;
ALTER TABLE article_assessments ADD COLUMN final_category TEXT;
ALTER TABLE article_assessments ADD COLUMN final_event_type TEXT;
ALTER TABLE article_assessments ADD COLUMN final_priority TEXT;
ALTER TABLE article_assessments ADD COLUMN final_tone TEXT;
ALTER TABLE article_assessments ADD COLUMN manual_override INTEGER NOT NULL DEFAULT 0;
