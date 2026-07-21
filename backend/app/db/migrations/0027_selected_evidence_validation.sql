-- 선택 기사 출처·본문 절대 오류와 정규화 근거를 추출 이력에 보존한다.
ALTER TABLE article_extractions ADD COLUMN canonical_url TEXT;
ALTER TABLE article_extractions ADD COLUMN page_publisher TEXT;
ALTER TABLE article_extractions ADD COLUMN source_domain TEXT;
ALTER TABLE article_extractions ADD COLUMN raw_source TEXT;
ALTER TABLE article_extractions ADD COLUMN normalized_source TEXT;
ALTER TABLE article_extractions ADD COLUMN normalization_reason TEXT;
ALTER TABLE article_extractions ADD COLUMN validation_errors_json TEXT NOT NULL DEFAULT '[]';
