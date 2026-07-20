-- AI 분석용 기사 원본/정제본과 추출 품질 이력을 원 기사와 분리해 보존한다.

CREATE TABLE IF NOT EXISTS article_extractions (
    id TEXT PRIMARY KEY,
    article_id TEXT NOT NULL REFERENCES articles(id),
    source_url TEXT,
    resolved_url TEXT,
    raw_text TEXT,
    cleaned_text TEXT,
    extraction_status TEXT NOT NULL,
    failure_reason TEXT,
    analysis_eligible INTEGER NOT NULL DEFAULT 0,
    raw_character_count INTEGER NOT NULL DEFAULT 0,
    cleaned_character_count INTEGER NOT NULL DEFAULT 0,
    extraction_attempts_json TEXT NOT NULL DEFAULT '[]',
    replacement_article_id TEXT REFERENCES articles(id),
    replaces_article_id TEXT REFERENCES articles(id),
    same_issue_id TEXT REFERENCES issues(id),
    cleaning_rule_version TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_article_extractions_article_created
ON article_extractions(article_id, created_at DESC);

CREATE TABLE IF NOT EXISTS publisher_extraction_events (
    id TEXT PRIMARY KEY,
    article_id TEXT NOT NULL REFERENCES articles(id),
    publisher_id TEXT,
    publisher_name TEXT,
    extraction_status TEXT NOT NULL,
    analysis_eligible INTEGER NOT NULL DEFAULT 0,
    noise_detected INTEGER NOT NULL DEFAULT 0,
    ai_content_detected INTEGER NOT NULL DEFAULT 0,
    access_blocked INTEGER NOT NULL DEFAULT 0,
    failure_reason TEXT,
    attempted_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_publisher_extraction_events_recent
ON publisher_extraction_events(publisher_id, attempted_at DESC);
