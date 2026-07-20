import { state, settings, els, CATEGORY_COLORS } from "../state/store.js";
import { escapeHtml, escapeAttr } from "../utils/strings.js";
import { formatRelative } from "../utils/dates.js";

export const MAX_TOP_ISSUES = 6;

function categoryDetails(article) {
  if (!article?.category) return null;
  const label = settings.queries.find(query => query.id === article.category)?.label || "기타";
  return { id: article.category, label, color: CATEGORY_COLORS[article.category] || "#326c9c" };
}

function categoryChips(articles) {
  const categories = [];
  const seen = new Set();
  articles.forEach(article => {
    const category = categoryDetails(article);
    if (!category || seen.has(category.id)) return;
    seen.add(category.id);
    categories.push(category);
  });
  const visible = categories.slice(0, 2).map(category =>
    `<span class="issue-category" style="--issue-category-color:${escapeAttr(category.color)}">${escapeHtml(category.label)}</span>`,
  );
  if (categories.length > 2) visible.push(`<span class="issue-category-more">+${categories.length - 2}</span>`);
  return visible.join("") || '<span class="issue-category muted">분류 미확정</span>';
}

function entryDate(entry) {
  return entry.kind === "issue" ? entry.item.lastSeenAt : entry.item.pubDate;
}

function sourceAndTime(source, date) {
  return `${source || "출처 미상"} · ${date ? formatRelative(date) : "일시 미상"}`;
}

export function getTopIssueEntries() {
  const groupedArticleIds = new Set(state.issues.flatMap(issue => issue.articleIds || []));
  const taggedIssues = state.issues.filter(issue => issue.selected).map(issue => ({
    kind: "issue",
    item: issue,
  }));
  const taggedArticles = state.articles.filter(article => article.topIssue && !groupedArticleIds.has(article.id)).map(article => ({
    kind: "article",
    item: article,
  }));
  return taggedIssues.concat(taggedArticles)
    .sort((left, right) => {
      const leftOrder = Number.isFinite(left.item.sortOrder) ? left.item.sortOrder : Number.MAX_SAFE_INTEGER;
      const rightOrder = Number.isFinite(right.item.sortOrder) ? right.item.sortOrder : Number.MAX_SAFE_INTEGER;
      return leftOrder - rightOrder
        || String(entryDate(right) || "").localeCompare(String(entryDate(left) || ""))
        || String(left.item.id).localeCompare(String(right.item.id));
    })
    .slice(0, MAX_TOP_ISSUES);
}

function orderControls(tagged, index, length) {
  const disabled = state.status === "final";
  const identity = `data-top-kind="${tagged.kind}" data-top-id="${escapeAttr(tagged.item.id)}"`;
  return `<div class="issue-order-controls no-print" aria-label="탑이슈 순서 변경">
    <button data-action="move-top-issue" data-direction="up" ${identity} title="한 칸 앞으로" aria-label="탑이슈를 한 칸 앞으로" ${disabled || index === 0 ? "disabled" : ""}>↑</button>
    <button data-action="move-top-issue" data-direction="down" ${identity} title="한 칸 뒤로" aria-label="탑이슈를 한 칸 뒤로" ${disabled || index === length - 1 ? "disabled" : ""}>↓</button>
  </div>`;
}

export function renderTopIssues() {
  const articleById = new Map(state.articles.map(article => [article.id, article]));
  const top = getTopIssueEntries();

  els.topIssues.innerHTML = Array.from({ length: MAX_TOP_ISSUES }, (_, index) => {
    const tagged = top[index];
    if (!tagged) return `<div class="issue-card empty"><div>ISSUE ${String(index + 1).padStart(2, "0")}</div><strong>Media Coverage에서 군집 또는 기사를 태그하세요</strong></div>`;
    if (tagged.kind === "article") {
      const article = tagged.item;
      const context = article.note || sourceAndTime(article.source, article.pubDate);
      return `<article class="issue-card">
        <div class="issue-head"><span class="rank">ISSUE ${String(index + 1).padStart(2, "0")}</span><div class="issue-head-actions">${orderControls(tagged, index, top.length)}<button class="issue-remove-btn no-print" data-action="remove-top-issue" data-article-id="${escapeAttr(article.id)}" ${state.status === "final" ? "disabled" : ""}>탑이슈 제거</button></div></div>
        <div class="issue-categories">${categoryChips([article])}</div>
        <h3>${escapeHtml(article.title)}</h3>
        <div class="issue-context">${escapeHtml(context)}</div>
      </article>`;
    }
    const issue = tagged.item;
    const articles = issue.articleIds.map(articleId => articleById.get(articleId)).filter(Boolean);
    const visibleRepresentative = articles.find(article => article.topIssue)
      || articleById.get(issue.representativeArticleId)
      || articles.find(article => article.included)
      || articles[0];
    const displayTitle = issue.editorTitle || visibleRepresentative?.title || issue.effectiveTitle;
    const orderedForCategories = visibleRepresentative
      ? [visibleRepresentative, ...articles.filter(article => article.id !== visibleRepresentative.id)]
      : articles;
    const context = issue.note
      || issue.editorReviewReason
      || sourceAndTime(visibleRepresentative?.source, visibleRepresentative?.pubDate || issue.lastSeenAt);
    return `<article class="issue-card">
      <div class="issue-head"><span class="rank">ISSUE ${String(index + 1).padStart(2, "0")}</span><div class="issue-head-actions">${orderControls(tagged, index, top.length)}<button class="issue-remove-btn no-print" data-action="remove-top-issue" data-issue-id="${escapeAttr(issue.id)}" ${state.status === "final" ? "disabled" : ""}>탑이슈 제거</button></div></div>
      <div class="issue-categories">${categoryChips(orderedForCategories)}</div>
      <h3>${escapeHtml(displayTitle)}</h3>
      <div class="issue-context">${escapeHtml(context)}</div>
    </article>`;
  }).join("");
}
