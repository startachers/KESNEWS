-- 관련도 미달로 본 파이프라인에서 제외된 기사를 '이슈 기사 찾아보기' 버튼 전용으로 보관한다.
-- 브리핑·후보 선정과 완전히 분리된 임시 풀이며, 보고일별로 최신 수집분만 유지한다.
CREATE TABLE IF NOT EXISTS dropped_article_pool (
    id TEXT PRIMARY KEY,
    collection_run_id TEXT NOT NULL REFERENCES collection_runs(id),
    report_date TEXT NOT NULL,
    title TEXT NOT NULL,
    normalized_title TEXT NOT NULL,
    url TEXT,
    source TEXT,
    published_at TEXT,
    description TEXT,
    category TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_dropped_pool_report_date
ON dropped_article_pool(report_date, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_dropped_pool_run
ON dropped_article_pool(collection_run_id);
