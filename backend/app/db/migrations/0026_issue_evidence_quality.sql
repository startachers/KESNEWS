-- 관련기사 본문 품질과 담당자 확정 근거 역할을 자동 군집 결과와 분리해 보존한다.

ALTER TABLE article_extractions ADD COLUMN content_quality_score INTEGER;
ALTER TABLE article_extractions ADD COLUMN quality_grade TEXT;
ALTER TABLE article_extractions ADD COLUMN quality_reasons_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE article_extractions ADD COLUMN complete_sentence_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE article_extractions ADD COLUMN contamination_flags_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE article_extractions ADD COLUMN extraction_method TEXT;

ALTER TABLE issues ADD COLUMN manual_representative_article_id TEXT REFERENCES articles(id);
ALTER TABLE issues ADD COLUMN manual_supplemental_article_ids_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE issues ADD COLUMN manual_excluded_article_ids_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE issues ADD COLUMN manual_selection_updated_at TEXT;
ALTER TABLE issues ADD COLUMN evidence_revision INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_issues_manual_representative
ON issues(manual_representative_article_id);
