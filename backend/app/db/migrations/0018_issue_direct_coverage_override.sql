-- 공사 직접 보도 자동 판정과 보고일별 담당자 override를 분리한다.
ALTER TABLE briefing_issues
ADD COLUMN direct_coverage_override INTEGER
CHECK (direct_coverage_override IS NULL OR direct_coverage_override IN (0, 1));

-- 기존 자동 판정 그룹은 일반 브리핑과 Top Issues에서 제거한다.
UPDATE briefing_articles
SET selected = 0,
    top_issue = 0,
    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
WHERE EXISTS (
    SELECT 1
    FROM briefings b
    JOIN issues i ON i.direct_mention = 1
    JOIN cluster_runs cr
      ON cr.id = i.last_cluster_run_id AND cr.report_date = b.report_date
    WHERE b.id = briefing_articles.briefing_id
      AND (
          EXISTS (
              SELECT 1 FROM issue_auto_articles iaa
              WHERE iaa.issue_id = i.id
                AND iaa.cluster_run_id = i.last_cluster_run_id
                AND iaa.article_id = briefing_articles.article_id
          )
          OR EXISTS (
              SELECT 1 FROM issue_membership_overrides added
              WHERE added.issue_id = i.id
                AND added.article_id = briefing_articles.article_id
                AND added.action = 'add'
          )
      )
      AND NOT EXISTS (
          SELECT 1 FROM issue_membership_overrides removed
          WHERE removed.issue_id = i.id
            AND removed.article_id = briefing_articles.article_id
            AND removed.action = 'remove'
      )
      AND NOT EXISTS (
          SELECT 1 FROM briefing_issues bi
          WHERE bi.briefing_id = b.id
            AND bi.issue_id = i.id
            AND bi.direct_coverage_override = 0
      )
);

UPDATE briefing_issues
SET selected = 0,
    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
WHERE direct_coverage_override IS NOT 0
  AND EXISTS (
      SELECT 1 FROM issues i
      WHERE i.id = briefing_issues.issue_id
        AND i.direct_mention = 1
  );
