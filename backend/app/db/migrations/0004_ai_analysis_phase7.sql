-- Phase 7: AI 실행별 입력, 고정 근거 index, 검증 결과와 오류를 보존한다.

CREATE TABLE IF NOT EXISTS ai_runs (
    id TEXT PRIMARY KEY,
    briefing_id TEXT NOT NULL REFERENCES briefings(id),
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    input_signature TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'success', 'failed')),
    request_json TEXT NOT NULL,
    response_json TEXT,
    evidence_json TEXT NOT NULL,
    error_message TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_ai_runs_briefing_started
ON ai_runs(briefing_id, started_at DESC);
