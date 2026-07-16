import { state, els } from "../state/store.js";
import { escapeHtml } from "../utils/strings.js";
import { formatRelative } from "../utils/dates.js";

const ISSUE_STATUS_LABELS = { new: "신규", expanding: "확산", ongoing: "지속", cooling: "진정", closed: "종료" };
const ISSUE_RISK = { required: "critical", review: "watch", reference: "routine" };

export function renderTopIssues() {
  const articleById = new Map(state.articles.map(article => [article.id, article]));
  const taggedIssues = state.issues.filter(issue => issue.selected).map(issue => ({
    kind: "issue",
    item: issue,
    date: issue.lastSeenAt || "",
  }));
  const taggedArticles = state.articles.filter(article => article.topIssue).map(article => ({
    kind: "article",
    item: article,
    date: article.pubDate || "",
  }));
  const top = taggedIssues.concat(taggedArticles)
    .sort((left, right) => String(right.date).localeCompare(String(left.date)))
    .slice(0, 3);

  els.topIssues.innerHTML = [0, 1, 2].map((_, index) => {
    const tagged = top[index];
    if (!tagged) return `<div class="issue-card empty"><div>ISSUE ${String(index + 1).padStart(2, "0")}</div><strong>Media Coverage에서 군집 또는 기사를 태그하세요</strong></div>`;
    if (tagged.kind === "article") {
      const article = tagged.item;
      return `<article class="issue-card">
        <div class="issue-head"><span class="rank">ISSUE ${String(index + 1).padStart(2, "0")}</span><span class="badge badge-${article.risk}">기사</span></div>
        <h3>${escapeHtml(article.title)}</h3>
        <div class="issue-meta">${escapeHtml(article.source || "출처 미상")} · ${formatRelative(article.pubDate)}</div>
        <div class="issue-reason">담당자가 개별 기사를 Top 이슈로 태그했습니다.</div>
      </article>`;
    }
    const issue = tagged.item;
    const articles = issue.articleIds.map(articleId => articleById.get(articleId)).filter(Boolean);
    const sourceCount = new Set(articles.map(article => article.source).filter(Boolean)).size;
    const risk = ISSUE_RISK[issue.effectivePriority] || "routine";
    const status = ISSUE_STATUS_LABELS[issue.effectiveStatus] || issue.effectiveStatus || "상태 없음";
    const pressCoverage = issue.autoReasons?.origin?.type === "kesco_press_release";
    const reason = pressCoverage
      ? `공사 보도자료에서 파생된 보도 ${issue.articleIds.length}건의 확산 묶음입니다.`
      : issue.articleIds.length > 1
        ? `같은 사건 기사 ${issue.articleIds.length}건이 묶인 이슈입니다.`
        : "단일 기사 이슈입니다.";
    return `<article class="issue-card">
      <div class="issue-head"><span class="rank">ISSUE ${String(index + 1).padStart(2, "0")}</span><span class="badge badge-${risk}">${escapeHtml(status)}</span></div>
      <h3>${escapeHtml(issue.effectiveTitle)}</h3>
      <div class="issue-meta">기사 ${issue.articleIds.length}건 · 매체 ${sourceCount}개 · ${formatRelative(issue.lastSeenAt)}</div>
      <div class="issue-reason">${escapeHtml(reason)}</div>
    </article>`;
  }).join("");
}
