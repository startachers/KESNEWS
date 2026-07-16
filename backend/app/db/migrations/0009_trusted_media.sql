-- 기사 수집 설계 변경 단계 3: 출처 판별과 실행별 필터 통계를 보존한다.
ALTER TABLE articles ADD COLUMN publisher_id TEXT;
ALTER TABLE articles ADD COLUMN publisher_allowed INTEGER;
ALTER TABLE collection_runs ADD COLUMN source_filter_stats_json TEXT;
