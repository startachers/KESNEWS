-- 정제 규칙이 바뀐 뒤 과거 판정을 현재 성공률과 섞지 않는다.
ALTER TABLE publisher_extraction_events ADD COLUMN cleaning_rule_version TEXT;
