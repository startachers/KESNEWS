-- 재군집화 전 단독 기사도 공사 직접 보도 자동 판정과 담당자 override를 보존한다.
ALTER TABLE briefing_articles
ADD COLUMN direct_coverage_override INTEGER
CHECK (direct_coverage_override IS NULL OR direct_coverage_override IN (0, 1));

UPDATE briefing_articles
SET selected = 0,
    top_issue = 0,
    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
WHERE EXISTS (
    SELECT 1
    FROM articles a
    LEFT JOIN article_assessments aa ON aa.article_id = a.id
    WHERE a.id = briefing_articles.article_id
      AND COALESCE(aa.final_category, aa.auto_category, a.category_hint) = 'kesco_direct'
)
AND NOT EXISTS (
    SELECT 1
    FROM briefings b
    JOIN issues i
    JOIN briefing_issues bi
      ON bi.briefing_id = b.id
     AND bi.issue_id = i.id
     AND bi.direct_coverage_override = 0
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
);
