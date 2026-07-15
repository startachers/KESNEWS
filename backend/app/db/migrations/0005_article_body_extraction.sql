-- 선정 기사 전문을 보존하고 AI 실행에서 재사용한다.

ALTER TABLE articles ADD COLUMN body_text TEXT;
ALTER TABLE articles ADD COLUMN body_fetched_at TEXT;
ALTER TABLE articles ADD COLUMN body_error TEXT;
