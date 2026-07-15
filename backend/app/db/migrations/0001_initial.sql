-- Phase 4 최소 스키마. issues/cluster_runs/ai_runs 등은 Phase 6~7에서 실제로 필요할 때 추가한다.

CREATE TABLE IF NOT EXISTS articles (
    id TEXT PRIMARY KEY,
    content_key TEXT NOT NULL UNIQUE,
    canonical_url TEXT,
    title TEXT NOT NULL,
    normalized_title TEXT,
    source TEXT,
    source_domain TEXT,
    published_at TEXT,
    first_observed_at TEXT NOT NULL,
    last_observed_at TEXT NOT NULL,
    description TEXT,
    body_status TEXT,
    category_hint TEXT,
    manual INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS collection_runs (
    id TEXT PRIMARY KEY,
    report_date TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    lookback_hours INTEGER,
    raw_count INTEGER NOT NULL DEFAULT 0,
    accepted_count INTEGER NOT NULL DEFAULT 0,
    unique_count INTEGER NOT NULL DEFAULT 0,
    stale_reused_count INTEGER NOT NULL DEFAULT 0,
    warning_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_collection_runs_report_date ON collection_runs(report_date);

CREATE TABLE IF NOT EXISTS collection_run_providers (
    id TEXT PRIMARY KEY,
    collection_run_id TEXT NOT NULL REFERENCES collection_runs(id),
    provider TEXT NOT NULL,
    query_group_id TEXT,
    status TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    raw_count INTEGER NOT NULL DEFAULT 0,
    accepted_count INTEGER NOT NULL DEFAULT 0,
    duplicate_count INTEGER NOT NULL DEFAULT 0,
    stale_reused_count INTEGER NOT NULL DEFAULT 0,
    warning_message TEXT,
    error_code TEXT,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_collection_run_providers_run ON collection_run_providers(collection_run_id);

CREATE TABLE IF NOT EXISTS article_observations (
    id TEXT PRIMARY KEY,
    article_id TEXT NOT NULL REFERENCES articles(id),
    collection_run_provider_id TEXT REFERENCES collection_run_providers(id),
    provider TEXT NOT NULL,
    provider_item_key TEXT,
    query_group_id TEXT,
    raw_url TEXT,
    raw_title TEXT,
    raw_source TEXT,
    raw_published_at TEXT,
    raw_description TEXT,
    raw_payload_json TEXT,
    observed_at TEXT NOT NULL,
    dedup_method TEXT,
    dedup_score REAL
);

CREATE INDEX IF NOT EXISTS idx_article_observations_article ON article_observations(article_id);

CREATE TABLE IF NOT EXISTS article_assessments (
    article_id TEXT PRIMARY KEY REFERENCES articles(id),
    auto_category TEXT,
    auto_risk TEXT,
    auto_risk_score INTEGER,
    auto_sentiment TEXT,
    auto_reasons_json TEXT,
    classifier_version TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS briefings (
    id TEXT PRIMARY KEY,
    report_date TEXT NOT NULL UNIQUE,
    prepared_by TEXT,
    status TEXT NOT NULL DEFAULT 'draft',
    situation_summary TEXT,
    action_note TEXT,
    summary_mode TEXT,
    ai_model TEXT,
    ai_prompt_version TEXT,
    ai_generated_at TEXT,
    ai_input_signature TEXT,
    revision INTEGER NOT NULL DEFAULT 0,
    latest_final_version INTEGER,
    finalized_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS briefing_versions (
    id TEXT PRIMARY KEY,
    briefing_id TEXT NOT NULL REFERENCES briefings(id),
    version INTEGER NOT NULL,
    source_revision INTEGER,
    snapshot_json TEXT NOT NULL,
    report_html_path TEXT,
    finalized_at TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(briefing_id, version)
);

CREATE TABLE IF NOT EXISTS briefing_articles (
    briefing_id TEXT NOT NULL REFERENCES briefings(id),
    article_id TEXT NOT NULL REFERENCES articles(id),
    selected INTEGER NOT NULL DEFAULT 0,
    starred INTEGER NOT NULL DEFAULT 0,
    note TEXT,
    dismissed INTEGER NOT NULL DEFAULT 0,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (briefing_id, article_id)
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
