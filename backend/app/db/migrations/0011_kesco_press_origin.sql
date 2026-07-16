-- KESCO 보도자료 원문과 언론기사의 파생 관계를 기사 원본/일반 판정과 분리해 보존한다.

CREATE TABLE IF NOT EXISTS kesco_press_releases (
    id TEXT PRIMARY KEY,
    bbs_seq TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    published_at TEXT,
    body_text TEXT,
    canonical_url TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_kesco_press_releases_published_at
ON kesco_press_releases(published_at DESC);

CREATE TABLE IF NOT EXISTS article_origin_assessments (
    article_id TEXT PRIMARY KEY REFERENCES articles(id),
    auto_origin_type TEXT NOT NULL CHECK (
        auto_origin_type IN ('kesco_republication', 'kesco_based')
    ),
    auto_press_release_id TEXT NOT NULL REFERENCES kesco_press_releases(id),
    auto_confidence REAL NOT NULL,
    auto_reasons_json TEXT NOT NULL,
    final_origin_type TEXT CHECK (
        final_origin_type IS NULL OR
        final_origin_type IN ('kesco_republication', 'kesco_based', 'independent')
    ),
    final_press_release_id TEXT REFERENCES kesco_press_releases(id),
    manual_override INTEGER NOT NULL DEFAULT 0,
    classifier_version TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_article_origin_press_release
ON article_origin_assessments(auto_press_release_id);
