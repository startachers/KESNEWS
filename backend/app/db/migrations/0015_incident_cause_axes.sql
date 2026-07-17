-- incident_json은 유연한 JSON 컬럼이므로 물리 컬럼 추가는 필요하지 않다.
-- 이 migration은 rules-v11 재분류 전에 운영 DB 백업 경계를 만들고,
-- cause_certainty/cause_domain 추가를 schema migration 이력에 남긴다.
SELECT 1;
