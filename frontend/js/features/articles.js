import { state, setState, settings, els, filters, setFilters, CATEGORY_COLORS, RISK_LABELS, SENTIMENT_LABELS, saveDailyState, loadDailyState } from "../state/store.js";
import { escapeHtml, escapeAttr, safeUrl, friendlyError } from "../utils/strings.js";
import { dateValue, formatDateTime } from "../utils/dates.js";
import { getRelevance, isYonhapArticle, relevanceSort, prioritySort } from "./collection.js";
import * as api from "../api/client.js";
import { ICONS } from "../ui/icons.js";
import { renderAll } from "../ui/renderers.js";
import { refreshRuleSummaryIfNeeded, renderAiSummaryStatus } from "./ai-analysis.js";
import { showToast } from "../ui/notifications.js";
import { runSearch } from "./collection.js";
import { loadSample } from "./data-io.js";

export function renderArticles() {
  const selectedCount = state.articles.filter(article => article.included).length;
  const selectedOnlyActive = filters.selection === "selected";
  els.selectedOnlyCount.textContent = selectedCount;
  els.selectedOnlyBtn.classList.toggle("active", selectedOnlyActive);
  els.selectedOnlyBtn.setAttribute("aria-pressed", String(selectedOnlyActive));
  els.selectedOnlyBtn.title = selectedOnlyActive ? "전체 기사 보기" : `선택한 기사 ${selectedCount}건만 보기`;
  let items = state.articles.filter(a => {
    const hay = `${a.title} ${a.source} ${a.description || ""} ${(a.matchedKeywords || []).join(" ")}`.toLowerCase();
    const selectionMatch = filters.selection === "all" || (filters.selection === "selected" && a.included) || (filters.selection === "starred" && a.starred) || (filters.selection === "unselected" && !a.included);
    return (!filters.text || hay.includes(filters.text)) && (filters.category === "all" || a.category === filters.category) && (filters.risk === "all" || a.risk === filters.risk) && selectionMatch;
  });
  if (filters.sort === "relevance") items.sort(relevanceSort);
  else if (filters.sort === "newest") items.sort((a,b) => dateValue(b.pubDate)-dateValue(a.pubDate));
  else if (filters.sort === "source") items.sort((a,b) => (a.source || "").localeCompare(b.source || "", "ko"));
  else items.sort(prioritySort);
  els.visibleCount.textContent = `${items.length}건 표시`;

  if (!state.articles.length) {
    els.articleList.innerHTML = `<div class="empty-state">
      <div class="empty-icon">${ICONS.search}</div><h3>아직 수집된 기사가 없습니다</h3>
      <p>‘오늘 기사 검색’으로 최근 보도를 모읍니다. 검색에서 빠진 기사 1건은 직접 등록하고, 이전 브리핑은 JSON 백업 또는 CSV 기사목록으로 불러올 수 있습니다.</p>
      <div class="empty-actions"><button class="btn btn-primary" data-action="search">오늘 기사 검색</button><button class="btn" data-action="sample">샘플 화면 보기</button></div>
    </div>`;
    return;
  }
  if (!items.length) {
    els.articleList.innerHTML = `<div class="empty-state"><h3>조건에 맞는 기사가 없습니다</h3><p>검색어나 필터를 초기화해 보세요.</p><div class="empty-actions"><button class="btn" data-action="clear-filters">필터 초기화</button></div></div>`;
    return;
  }

  els.articleList.innerHTML = items.map(a => {
    const category = settings.queries.find(q => q.id === a.category)?.label || "기타";
    const relevance = getRelevance(a);
    const href = safeUrl(a.url);
    const titleEl = href ? `<a class="article-title" href="${escapeAttr(href)}" target="_blank" rel="noopener noreferrer">${escapeHtml(a.title)}</a>` : `<span class="article-title">${escapeHtml(a.title)}</span>`;
    const relevanceBadge = relevance.rank < 99 ? `관련 ${relevance.rank}순위` : "관련 기준 외";
    const badges = [`<span class="badge badge-relevance ${relevance.rank <= 2 ? "top" : ""}" title="${escapeAttr(`${relevance.label} · ${relevance.reasons.join(" · ")}`)}">${escapeHtml(relevanceBadge)}</span>`, `<span class="badge badge-${a.risk}">${RISK_LABELS[a.risk]}</span>`, `<span class="badge badge-${a.sentiment}">${SENTIMENT_LABELS[a.sentiment]}</span>`];
    if (isYonhapArticle(a)) badges.unshift('<span class="badge badge-yonhap">연합뉴스 우선</span>');
    if (a.included) badges.push('<span class="badge badge-selected">브리핑 선정</span>');
    if (a.manual) badges.push('<span class="badge badge-manual">직접 추가</span>');
    if (a.isDemo) badges.push('<span class="badge badge-watch">샘플</span>');
    if (a.stale) badges.push('<span class="badge badge-watch" title="이전 수집 실패로 최신 상태를 확인하지 못했습니다">최신 미확인</span>');
    return `<article class="article-card ${a.included ? "included" : ""}" data-id="${escapeAttr(a.id)}">
      <input class="include-check" type="checkbox" aria-label="브리핑 선정" title="브리핑 선정" data-action="include" ${a.included ? "checked" : ""} ${state.status === "final" ? "disabled" : ""}>
      <div class="article-main">
        <div class="article-badges"><span class="category-label" style="color:${CATEGORY_COLORS[a.category] || "#326c9c"}">${escapeHtml(category)}</span>${badges.join("")}</div>
        ${titleEl}
        <div class="article-meta"><strong>${escapeHtml(a.source || "출처 미상")}</strong><span>${formatDateTime(a.pubDate)}</span><span>${escapeHtml(relevance.reasons.join(" · "))}</span><span>${escapeHtml((a.matchedKeywords || []).slice(0,4).join(" · ") || "키워드 자동 분류")}</span></div>
        ${a.description ? `<p class="article-desc">${escapeHtml(a.description)}</p>` : ""}
        <input class="article-note" data-action="note" value="${escapeAttr(a.note || "")}" aria-label="기사 메모" placeholder="보고 메모 추가 (인쇄에는 포함되지 않음)" ${state.status === "final" ? "disabled" : ""}>
      </div>
      <div class="article-actions">
        <button class="small-icon ${a.starred ? "active" : ""}" data-action="star" title="중요 기사" aria-label="중요 기사" ${state.status === "final" ? "disabled" : ""}>${ICONS.star}</button>
        <button class="small-icon" data-action="delete" title="기사 삭제" aria-label="기사 삭제" ${state.status === "final" ? "disabled" : ""}>${ICONS.trash}</button>
      </div>
    </article>`;
  }).join("");
}

export function handleArticleChange(e) {
  if (state.status === "final") return;
  const card = e.target.closest(".article-card"); if (!card) return;
  const article = state.articles.find(a => a.id === card.dataset.id); if (!article) return;
  if (e.target.dataset.action === "include") {
    article.included = e.target.checked;
    afterArticleMutation();
    trackArticlePatch(article.id, { selected: article.included });
    showToast(article.included ? "브리핑 기사로 선정했습니다." : "브리핑 선정을 해제했습니다.", article.included ? "success" : "");
  }
}

export function handleArticleInput(e) {
  if (state.status === "final") return;
  if (e.target.dataset.action !== "note") return;
  const card = e.target.closest(".article-card");
  const article = state.articles.find(a => a.id === card?.dataset.id);
  if (article) {
    article.note = e.target.value;
    state.summaryError = "";
    if (["ai", "ai-edited"].includes(state.summaryMode)) state.aiStale = true;
    renderAiSummaryStatus();
    patchArticleDebounced(article.id, { note: article.note });
  }
}

export function handleArticleClick(e) {
  const action = e.target.closest("[data-action]")?.dataset.action;
  if (action === "search") return runSearch(false);
  if (action === "sample") return loadSample();
  if (action === "clear-filters") {
    setFilters({ text: "", category: "all", risk: "all", selection: "all", sort: "relevance" });
    els.articleSearch.value = ""; els.categoryFilter.value = "all"; els.riskFilter.value = "all"; els.selectionFilter.value = "all"; els.sortOrder.value = "relevance"; renderArticles(); return;
  }
  if (!action) return;
  if (state.status === "final") return;
  const card = e.target.closest(".article-card");
  const article = state.articles.find(a => a.id === card?.dataset.id); if (!article) return;
  if (action === "star") { article.starred = !article.starred; afterArticleMutation(); trackArticlePatch(article.id, { starred: article.starred }); }
  if (action === "delete") {
    state.articles = state.articles.filter(a => a.id !== article.id);
    afterArticleMutation();
    trackArticlePatch(article.id, { dismissed: true });
    showToast("기사를 브리핑에서 삭제했습니다(휴지통으로 이동, 메모·중요 표시는 보존됩니다).");
  }
}

export function afterArticleMutation() {
  state.summaryError = "";
  if (["ai", "ai-edited"].includes(state.summaryMode)) state.aiStale = true;
  refreshRuleSummaryIfNeeded();
  persistAndRender();
}

export function persistAndRender() { saveDailyState(); renderAll(); }

const noteDebounceTimers = new Map();

/** 기사별 선택·중요·메모·휴지통 상태를 서버에 반영한다. revision 충돌 시 최신 상태를 다시 불러온다. */
export async function patchArticle(articleId, fields) {
  try {
    const result = await api.patchBriefingArticle(state.date, articleId, state.revision, fields);
    state.revision = result.data.revision;
    return true;
  } catch (error) {
    if (error.code === "BRIEFING_REVISION_CONFLICT") {
      showToast("다른 화면에서 변경 사항이 있어 최신 내용을 다시 불러옵니다.", "error");
      setState(await loadDailyState(state.date));
      renderAll();
    } else {
      showToast(`저장 실패: ${friendlyError(error)}`, "error");
    }
    return false;
  }
}

export function patchArticleDebounced(articleId, fields) {
  const pending = noteDebounceTimers.get(articleId);
  window.clearTimeout(pending?.timer);
  const timer = window.setTimeout(() => {
    noteDebounceTimers.delete(articleId);
    trackArticlePatch(articleId, fields);
  }, 500);
  noteDebounceTimers.set(articleId, { timer, fields });
}

const pendingArticleSaves = new Set();

function trackArticlePatch(articleId, fields) {
  const promise = patchArticle(articleId, fields);
  pendingArticleSaves.add(promise);
  promise.finally(() => pendingArticleSaves.delete(promise));
  return promise;
}

export async function flushArticleChanges() {
  for (const [articleId, pending] of noteDebounceTimers) {
    window.clearTimeout(pending.timer);
    noteDebounceTimers.delete(articleId);
    trackArticlePatch(articleId, pending.fields);
  }
  const results = await Promise.all([...pendingArticleSaves]);
  if (results.some(result => !result)) throw new Error("기사 변경사항을 저장하지 못했습니다.");
}
