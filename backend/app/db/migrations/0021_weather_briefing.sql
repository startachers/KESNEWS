CREATE TABLE IF NOT EXISTS weather_collection_runs (
    id TEXT PRIMARY KEY,
    report_date TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    context_id TEXT REFERENCES weather_contexts(id),
    warning_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_weather_runs_report_date
ON weather_collection_runs(report_date, started_at DESC);

CREATE TABLE IF NOT EXISTS weather_run_providers (
    id TEXT PRIMARY KEY,
    weather_collection_run_id TEXT NOT NULL REFERENCES weather_collection_runs(id),
    provider TEXT NOT NULL,
    status TEXT NOT NULL,
    issued_at TEXT,
    fetched_at TEXT,
    item_count INTEGER NOT NULL DEFAULT 0,
    error_code TEXT,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_weather_run_providers_run
ON weather_run_providers(weather_collection_run_id);

CREATE TABLE IF NOT EXISTS weather_observations (
    id TEXT PRIMARY KEY,
    weather_run_provider_id TEXT NOT NULL REFERENCES weather_run_providers(id),
    provider TEXT NOT NULL,
    product TEXT NOT NULL,
    request_key TEXT NOT NULL,
    official_issued_at TEXT,
    observed_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_weather_observations_provider
ON weather_observations(provider, observed_at DESC);

CREATE TABLE IF NOT EXISTS weather_contexts (
    id TEXT PRIMARY KEY,
    report_date TEXT NOT NULL,
    period_from TEXT NOT NULL,
    period_to TEXT NOT NULL,
    overall_level TEXT NOT NULL,
    issued_at TEXT,
    built_at TEXT NOT NULL,
    region_config_version TEXT NOT NULL,
    risk_rule_version TEXT NOT NULL,
    source_status_json TEXT NOT NULL,
    daily_summaries_json TEXT NOT NULL,
    alerts_json TEXT NOT NULL,
    input_signature TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(report_date, input_signature)
);

CREATE INDEX IF NOT EXISTS idx_weather_contexts_report_date
ON weather_contexts(report_date, built_at DESC);

CREATE TABLE IF NOT EXISTS weather_risk_signals (
    id TEXT PRIMARY KEY,
    weather_context_id TEXT NOT NULL REFERENCES weather_contexts(id),
    signal_key TEXT NOT NULL,
    hazard TEXT NOT NULL,
    level TEXT NOT NULL,
    starts_at TEXT,
    ends_at TEXT,
    region_ids_json TEXT NOT NULL,
    electrical_risks_json TEXT NOT NULL,
    recommended_checks_json TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    confidence TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(weather_context_id, signal_key)
);

CREATE INDEX IF NOT EXISTS idx_weather_signals_context
ON weather_risk_signals(weather_context_id);

CREATE TABLE IF NOT EXISTS briefing_weather (
    briefing_id TEXT PRIMARY KEY REFERENCES briefings(id),
    weather_context_id TEXT NOT NULL REFERENCES weather_contexts(id),
    include_in_report INTEGER NOT NULL DEFAULT 0,
    review_status TEXT NOT NULL DEFAULT 'pending',
    editor_note TEXT,
    attached_at TEXT NOT NULL,
    reviewed_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS briefing_weather_signals (
    briefing_id TEXT NOT NULL REFERENCES briefings(id),
    weather_context_id TEXT NOT NULL REFERENCES weather_contexts(id),
    weather_risk_signal_id TEXT NOT NULL REFERENCES weather_risk_signals(id),
    selected INTEGER NOT NULL DEFAULT 0,
    editor_level TEXT,
    editor_note TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (briefing_id, weather_risk_signal_id)
);

CREATE INDEX IF NOT EXISTS idx_briefing_weather_signals_briefing
ON briefing_weather_signals(briefing_id);
