-- Phase 6: 자동 이슈 그룹과 담당자 편집/구성 override를 분리한다.

CREATE TABLE IF NOT EXISTS cluster_runs (
    id TEXT PRIMARY KEY,
    report_date TEXT NOT NULL,
    status TEXT NOT NULL,
    input_signature TEXT NOT NULL,
    proposal_json TEXT NOT NULL,
    diff_json TEXT NOT NULL,
    algorithm_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    applied_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_cluster_runs_report_date
ON cluster_runs(report_date, created_at);

CREATE TABLE IF NOT EXISTS issues (
    id TEXT PRIMARY KEY,
    representative_article_id TEXT REFERENCES articles(id),
    auto_title TEXT,
    editor_title TEXT,
    auto_status TEXT,
    editor_status TEXT,
    auto_priority TEXT,
    editor_priority TEXT,
    auto_priority_score INTEGER,
    spread_score INTEGER NOT NULL DEFAULT 0,
    auto_reasons_json TEXT,
    first_seen_at TEXT,
    last_seen_at TEXT,
    direct_mention INTEGER NOT NULL DEFAULT 0,
    needs_review INTEGER NOT NULL DEFAULT 0,
    last_cluster_run_id TEXT REFERENCES cluster_runs(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS issue_auto_articles (
    issue_id TEXT NOT NULL REFERENCES issues(id),
    article_id TEXT NOT NULL REFERENCES articles(id),
    cluster_run_id TEXT NOT NULL REFERENCES cluster_runs(id),
    similarity_score REAL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (issue_id, article_id, cluster_run_id)
);

CREATE INDEX IF NOT EXISTS idx_issue_auto_articles_article
ON issue_auto_articles(article_id);

CREATE TABLE IF NOT EXISTS issue_membership_overrides (
    issue_id TEXT NOT NULL REFERENCES issues(id),
    article_id TEXT NOT NULL REFERENCES articles(id),
    action TEXT NOT NULL CHECK (action IN ('add', 'remove')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (issue_id, article_id)
);

CREATE TABLE IF NOT EXISTS briefing_issues (
    briefing_id TEXT NOT NULL REFERENCES briefings(id),
    issue_id TEXT NOT NULL REFERENCES issues(id),
    selected INTEGER NOT NULL DEFAULT 0,
    starred INTEGER NOT NULL DEFAULT 0,
    note TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (briefing_id, issue_id)
);
