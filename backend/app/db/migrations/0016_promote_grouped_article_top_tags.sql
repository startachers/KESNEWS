-- 군집 구성 기사에 남아 화면에서 숨겨진 개별 Top 태그를 군집 Top 태그로 승격한다.
WITH mapped AS (
    SELECT
        ba.briefing_id,
        ba.article_id,
        (
            SELECT i.id
            FROM issues i
            JOIN cluster_runs cr ON cr.id = i.last_cluster_run_id
            WHERE cr.report_date = b.report_date
              AND (
                  EXISTS (
                      SELECT 1 FROM issue_auto_articles iaa
                      WHERE iaa.issue_id = i.id
                        AND iaa.cluster_run_id = i.last_cluster_run_id
                        AND iaa.article_id = ba.article_id
                  )
                  OR EXISTS (
                      SELECT 1 FROM issue_membership_overrides added
                      WHERE added.issue_id = i.id
                        AND added.article_id = ba.article_id
                        AND added.action = 'add'
                  )
              )
              AND NOT EXISTS (
                  SELECT 1 FROM issue_membership_overrides removed
                  WHERE removed.issue_id = i.id
                    AND removed.article_id = ba.article_id
                    AND removed.action = 'remove'
              )
            ORDER BY i.manual_group DESC, i.updated_at DESC, i.id
            LIMIT 1
        ) AS issue_id
    FROM briefing_articles ba
    JOIN briefings b ON b.id = ba.briefing_id
    WHERE ba.top_issue = 1
), ranked AS (
    SELECT
        briefing_id,
        issue_id,
        ROW_NUMBER() OVER (PARTITION BY briefing_id ORDER BY issue_id) AS position
    FROM (SELECT DISTINCT briefing_id, issue_id FROM mapped WHERE issue_id IS NOT NULL)
)
INSERT INTO briefing_issues (
    briefing_id, issue_id, selected, starred, note, sort_order, created_at, updated_at
)
SELECT
    ranked.briefing_id,
    ranked.issue_id,
    1,
    0,
    NULL,
    COALESCE((
        SELECT MAX(existing.sort_order) + 1
        FROM briefing_issues existing
        WHERE existing.briefing_id = ranked.briefing_id
    ), 0) + ranked.position - 1,
    strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
    strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
FROM ranked
WHERE 1
ON CONFLICT(briefing_id, issue_id) DO UPDATE SET
    selected = 1,
    updated_at = excluded.updated_at;

WITH mapped AS (
    SELECT
        ba.briefing_id,
        ba.article_id
    FROM briefing_articles ba
    JOIN briefings b ON b.id = ba.briefing_id
    WHERE ba.top_issue = 1
      AND EXISTS (
          SELECT 1
          FROM issues i
          JOIN cluster_runs cr ON cr.id = i.last_cluster_run_id
          WHERE cr.report_date = b.report_date
            AND (
                EXISTS (
                    SELECT 1 FROM issue_auto_articles iaa
                    WHERE iaa.issue_id = i.id
                      AND iaa.cluster_run_id = i.last_cluster_run_id
                      AND iaa.article_id = ba.article_id
                )
                OR EXISTS (
                    SELECT 1 FROM issue_membership_overrides added
                    WHERE added.issue_id = i.id
                      AND added.article_id = ba.article_id
                      AND added.action = 'add'
                )
            )
            AND NOT EXISTS (
                SELECT 1 FROM issue_membership_overrides removed
                WHERE removed.issue_id = i.id
                  AND removed.article_id = ba.article_id
                  AND removed.action = 'remove'
            )
      )
)
UPDATE briefing_articles
SET top_issue = 0,
    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
WHERE EXISTS (
    SELECT 1 FROM mapped
    WHERE mapped.briefing_id = briefing_articles.briefing_id
      AND mapped.article_id = briefing_articles.article_id
);
