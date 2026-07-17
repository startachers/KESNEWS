-- Top Issues는 일반 브리핑에 포함된 기사 중 핵심 항목이므로 대표 기사 선정을 보장한다.
INSERT INTO briefing_articles (
    briefing_id, article_id, selected, starred, top_issue, note, dismissed,
    sort_order, created_at, updated_at
)
SELECT
    bi.briefing_id,
    i.representative_article_id,
    1,
    0,
    0,
    NULL,
    0,
    COALESCE((
        SELECT MAX(existing.sort_order) + 1
        FROM briefing_articles existing
        WHERE existing.briefing_id = bi.briefing_id
    ), 0),
    strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
    strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
FROM briefing_issues bi
JOIN issues i ON i.id = bi.issue_id
WHERE bi.selected = 1
  AND i.representative_article_id IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM briefing_articles existing
      WHERE existing.briefing_id = bi.briefing_id
        AND existing.article_id = i.representative_article_id
  );

UPDATE briefing_articles
SET selected = 1,
    dismissed = 0,
    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
WHERE EXISTS (
    SELECT 1
    FROM briefing_issues bi
    JOIN issues i ON i.id = bi.issue_id
    WHERE bi.briefing_id = briefing_articles.briefing_id
      AND bi.selected = 1
      AND i.representative_article_id = briefing_articles.article_id
);

UPDATE briefing_articles
SET selected = 1,
    dismissed = 0,
    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
WHERE top_issue = 1;
