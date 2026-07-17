export function primaryIssueByArticle(issues) {
  const issueByArticle = new Map();
  issues.filter(issue => issue.selected).forEach(issue => {
    issue.articleIds?.forEach(articleId => {
      if (!issueByArticle.has(articleId)) issueByArticle.set(articleId, issue);
    });
  });
  issues.forEach(issue => {
    issue.articleIds?.forEach(articleId => {
      if (!issueByArticle.has(articleId)) issueByArticle.set(articleId, issue);
    });
  });
  return issueByArticle;
}
