import { state, els } from "../state/store.js";
import { escapeHtml } from "../utils/strings.js";
import { formatRelative } from "../utils/dates.js";

const ISSUE_STATUS_LABELS = { new: "신규", expanding: "확산", ongoing: "지속", cooling: "진정", closed: "종료" };
export const MAX_TOP_ISSUES = 6;
function starsText(value) {
  const stars = Math.max(1, Math.min(5, Number(value) || 1));
  return `${"★".repeat(stars)}${"☆".repeat(5 - stars)}`;
}

export function renderTopIssues() {
  const articleById = new Map(state.articles.map(article => [article.id, article]));
  const groupedArticleIds = new Set(state.issues.flatMap(issue => issue.articleIds || []));
  const taggedIssues = state.issues.filter(issue => issue.selected).map(issue => ({
    kind: "issue",
    item: issue,
    date: issue.lastSeenAt || "",
  }));
  const taggedArticles = state.articles.filter(article => article.topIssue && !groupedArticleIds.has(article.id)).map(article => ({
    kind: "article",
    item: article,
    date: article.pubDate || "",
  }));
  const top = taggedIssues.concat(taggedArticles)
    .sort((left, right) => String(right.date).localeCompare(String(left.date)))
    .slice(0, MAX_TOP_ISSUES);

  els.topIssues.innerHTML = Array.from({ length: MAX_TOP_ISSUES }, (_, index) => {
    const tagged = top[index];
    if (!tagged) return `<div class="issue-card empty"><div>ISSUE ${String(index + 1).padStart(2, "0")}</div><strong>Media Coverage에서 군집 또는 기사를 태그하세요</strong></div>`;
    if (tagged.kind === "article") {
      const article = tagged.item;
      return `<article class="issue-card">
        <div class="issue-head"><span class="rank">ISSUE ${String(index + 1).padStart(2, "0")}</span><div class="issue-head-actions"><span class="badge badge-neutral">기사</span><button class="issue-remove-btn no-print" data-action="remove-top-issue" data-article-id="${escapeHtml(article.id)}" ${state.status === "final" ? "disabled" : ""}>탑이슈 제거</button></div></div>
        <h3>${escapeHtml(article.title)}</h3>
        <div class="issue-meta">${escapeHtml(article.source || "출처 미상")} · ${formatRelative(article.pubDate)}</div>
        <div class="issue-reason">담당자 태그 또는 확인·적용한 Gemma 핵심 추천 기사입니다.</div>
      </article>`;
    }
    const issue = tagged.item;
    const articles = issue.articleIds.map(articleId => articleById.get(articleId)).filter(Boolean);
    const visibleRepresentative = articles.find(article => article.topIssue)
      || articleById.get(issue.representativeArticleId)
      || articles.find(article => article.included)
      || articles[0];
    const displayTitle = issue.editorTitle || visibleRepresentative?.title || issue.effectiveTitle;
    const sourceCount = new Set(articles.map(article => article.source).filter(Boolean)).size;
    const status = ISSUE_STATUS_LABELS[issue.effectiveStatus] || issue.effectiveStatus || "상태 없음";
    const pressCoverage = issue.autoReasons?.origin?.type === "kesco_press_release";
    const reason = pressCoverage
      ? `공사 보도자료에서 파생된 보도 ${issue.articleIds.length}건의 확산 묶음입니다.`
      : issue.articleIds.length > 1
        ? `같은 사건 기사 ${issue.articleIds.length}건이 묶인 이슈입니다.`
        : "단일 기사 이슈입니다.";
    return `<article class="issue-card">
      <div class="issue-head"><span class="rank">ISSUE ${String(index + 1).padStart(2, "0")}</span><div class="issue-head-actions"><span class="review-stars">${starsText(issue.effectiveReviewStars)}</span><button class="issue-remove-btn no-print" data-action="remove-top-issue" data-issue-id="${escapeHtml(issue.id)}" ${state.status === "final" ? "disabled" : ""}>탑이슈 제거</button></div></div>
      <h3>${escapeHtml(displayTitle)}</h3>
      <div class="issue-meta">자동 ${issue.autoReviewRank || "-"}위 · 점수 ${issue.autoReviewScore ?? "-"} · ${escapeHtml(status)} · 기사 ${issue.articleIds.length}건 · 매체 ${sourceCount}개 · ${formatRelative(issue.lastSeenAt)}</div>
      <div class="issue-reason">${escapeHtml(reason)}</div>
    </article>`;
  }).join("");
}
