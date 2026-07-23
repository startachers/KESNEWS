-- 담당자가 확인해 붙여넣은 기사 본문을 자동 수집 원문과 분리해 보존한다.
CREATE TABLE IF NOT EXISTS article_body_overrides (
    article_id TEXT PRIMARY KEY REFERENCES articles(id),
    extraction_id TEXT NOT NULL REFERENCES article_extractions(id),
    raw_text TEXT NOT NULL,
    cleaned_text TEXT NOT NULL,
    source_url TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

