-- 외부 고성능 AI 결과와 담당자 수정본을 Gemma 실행 기록과 분리해 보존한다.

CREATE TABLE IF NOT EXISTS briefing_report_drafts (
    briefing_id TEXT PRIMARY KEY REFERENCES briefings(id),
    source_type TEXT NOT NULL CHECK (source_type IN ('gemma', 'external', 'manual')),
    source_label TEXT,
    content_json TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    input_signature TEXT NOT NULL,
    based_on_ai_run_id TEXT REFERENCES ai_runs(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
