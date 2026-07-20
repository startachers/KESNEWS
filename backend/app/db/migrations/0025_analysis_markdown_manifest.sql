-- 저장된 분석 Markdown의 서명·근거표를 외부 AI 결과 검증과 연결한다.

CREATE TABLE IF NOT EXISTS briefing_analysis_markdown (
    briefing_id TEXT PRIMARY KEY REFERENCES briefings(id) ON DELETE CASCADE,
    source_signature TEXT NOT NULL,
    input_signature TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    file_hash TEXT NOT NULL,
    md_path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
