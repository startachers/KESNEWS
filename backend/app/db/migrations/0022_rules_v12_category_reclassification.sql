-- rules-v12 재분류 전 운영 DB 자동 백업 경계를 만든다.
-- 스키마 변경은 없으며 init_db의 classifier_version backfill이 auto_*만 갱신한다.
-- final_* 수동 판정과 briefing_versions 불변 snapshot은 변경하지 않는다.
SELECT 1;
