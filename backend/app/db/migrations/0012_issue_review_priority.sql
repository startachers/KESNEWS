-- 군집 단위 5단계 검토순위. 순위는 보고일 후보 집합에 상대적이므로 issues가 아니라
-- briefing_id + issue_id에 저장한다. editor_* 값은 자동 재계산으로 덮어쓰지 않는다.

CREATE TABLE IF NOT EXISTS issue_review_assessments (
    briefing_id TEXT NOT NULL REFERENCES briefings(id),
    issue_id TEXT NOT NULL REFERENCES issues(id),
    auto_score INTEGER,
    auto_rank INTEGER,
    auto_stars INTEGER CHECK (auto_stars BETWEEN 1 AND 5),
    editor_stars INTEGER CHECK (editor_stars BETWEEN 1 AND 5),
    editor_reason TEXT,
    reasons_json TEXT NOT NULL DEFAULT '{}',
    scoring_version TEXT NOT NULL DEFAULT 'review-v1',
    calculated_at TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (briefing_id, issue_id)
);

CREATE INDEX IF NOT EXISTS idx_issue_review_briefing_rank
ON issue_review_assessments(briefing_id, auto_rank);
