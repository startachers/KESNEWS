-- Gemma 기사 추천은 실제 브리핑 선정 상태와 분리해 실행·오류·적용 이력을 보존한다.

CREATE TABLE IF NOT EXISTS ai_selection_runs (
    id TEXT PRIMARY KEY,
    briefing_id TEXT NOT NULL REFERENCES briefings(id),
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    input_signature TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'success', 'failed', 'applied')),
    request_json TEXT NOT NULL,
    response_json TEXT,
    evidence_json TEXT NOT NULL,
    error_message TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    applied_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_ai_selection_runs_briefing_started
ON ai_selection_runs(briefing_id, started_at DESC);
