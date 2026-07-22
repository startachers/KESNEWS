import { state, setState, settings, els, filters, setFilters, CATEGORY_COLORS, SENTIMENT_LABELS, saveDailyState, loadDailyState } from "../state/store.js";
import { escapeHtml, escapeAttr, safeUrl, friendlyError } from "../utils/strings.js";
import { primaryIssueByArticle } from "../utils/issues.js";
import { dateValue, formatDateTime } from "../utils/dates.js";
import { getRelevance, isYonhapArticle, relevanceSort, prioritySort } from "./collection.js";
import * as api from "../api/client.js";
import { ICONS } from "../ui/icons.js";
import { renderAll } from "../ui/renderers.js";
import { refreshRuleSummaryIfNeeded, renderAiSummaryStatus } from "./ai-analysis.js";
import { showToast } from "../ui/notifications.js?v=20260716-1";
import { runSearch } from "./collection.js";
import { loadSample } from "./data-io.js";
import { getTopIssueEntries, MAX_TOP_ISSUES } from "./issues.js?v=20260720-2";

const expandedIssueIds = new Set();
const expandedPreviewKeys = new Set();
const collapsedRepresentativePreviewKeys = new Set();
const qualitySortedIssueIds = new Set();
const reextractingIssueIds = new Set();
const searchingRelatedArticleIds = new Set();
const manualGroupSelection = new Set();
const manualGroupSelectedKeys = new Set();
const evidenceFailureByArticleId = new Map();
const evidenceFailureByIssueId = new Map();
let manualGroupPickerEntries = new Map();
let manualGroupSearchText = "";

const EVIDENCE_ERROR_LABELS = {
  body_truncated: "본문 불완전",
  body_contaminated: "본문 오염 감지",
  body_unavailable: "본문 미확보",
  publisher_identity_mismatch: "출처 확인 필요",
  canonical_url_unresolved: "원문 주소 확인 필요",
  ai_generated_content_remains: "언론사 AI 콘텐츠 잔존",
};

const EVIDENCE_ERROR_MESSAGES = {
  body_truncated: "기사 본문 또는 요약이 문장 중간에서 잘렸습니다.",
  body_contaminated: "기사 본문 뒤에 추천기사 또는 다른 기사 내용이 포함돼 있습니다.",
  body_unavailable: "AI 분석에 사용할 기사 본문을 확보하지 못했습니다.",
  publisher_identity_mismatch: "표시된 언론사와 실제 원문 발행사가 일치하지 않습니다.",
  canonical_url_unresolved: "실제 기사 원문 주소를 확인하지 못했습니다.",
  ai_generated_content_remains: "언론사 AI 해설 또는 AI 생성 콘텐츠가 정제 본문에 남아 있습니다.",
};

function evidenceFailureReason(failure) {
  return (failure?.errors || [])
    .map(item => typeof item === "string" ? item : (item?.message || item?.code || ""))
    .filter(Boolean)
    .join(" · ") || "대표 근거 기사를 다시 지정해야 합니다.";
}

function evidenceFailureFor(articleId, issueId = "") {
  return evidenceFailureByArticleId.get(articleId) || evidenceFailureByIssueId.get(issueId) || null;
}

export function setEvidenceValidationFailures(failures = []) {
  evidenceFailureByArticleId.clear();
  evidenceFailureByIssueId.clear();
  failures.forEach(failure => {
    if (failure.articleId) evidenceFailureByArticleId.set(failure.articleId, failure);
    else if (failure.issueId) evidenceFailureByIssueId.set(failure.issueId, failure);
  });
}

function isKescoPressArticle(article) {
  return ["kesco_republication", "kesco_based"].includes(article.origin?.effectiveType);
}

function isKescoPressIssue(issue) {
  return issue?.autoReasons?.origin?.type === "kesco_press_release";
}

function starsText(value) {
  const stars = Math.max(1, Math.min(5, Number(value) || 1));
  return `${"★".repeat(stars)}${"☆".repeat(5 - stars)}`;
}

export function collectionOrderSort(a, b, relatedCounts = new Map()) {
  return (relatedCounts.get(b.id) || 0) - (relatedCounts.get(a.id) || 0)
    || dateValue(a.firstObservedAt) - dateValue(b.firstObservedAt)
    || relevanceSort(a, b);
}

function relatedArticleCounts() {
  const counts = new Map();
  state.issues.forEach(issue => {
    const relatedCount = Math.max(0, (issue.articleIds?.length || 0) - 1);
    issue.articleIds?.forEach(articleId => counts.set(
      articleId,
      Math.max(counts.get(articleId) || 0, relatedCount),
    ));
  });
  return counts;
}

function topIssueTagCount() {
  const groupedArticleIds = new Set(state.issues.flatMap(issue => issue.articleIds || []));
  return state.issues.filter(issue => issue.selected).length
    + state.articles.filter(article => article.topIssue && !groupedArticleIds.has(article.id)).length;
}

function renderArticleCard(a, issue = null, relatedMembers = []) {
  const category = settings.queries.find(q => q.id === a.category)?.label || "기타";
  const relevance = getRelevance(a);
  const href = safeUrl(a.url);
  const titleEl = href ? `<a class="article-title" href="${escapeAttr(href)}" target="_blank" rel="noopener noreferrer">${escapeHtml(a.title)}</a>` : `<span class="article-title">${escapeHtml(a.title)}</span>`;
  const relevanceBadge = relevance.rank < 99 ? `관련 ${relevance.rank}순위` : "관련 기준 외";
  const badges = [`<span class="badge badge-relevance ${relevance.rank <= 2 ? "top" : ""}" title="${escapeAttr(`${relevance.label} · ${relevance.reasons.join(" · ")}`)}">${escapeHtml(relevanceBadge)}</span>`, `<span class="badge badge-${a.sentiment}">${SENTIMENT_LABELS[a.sentiment]}</span>`];
  const evidenceFailure = evidenceFailureFor(a.id, issue?.id);
  if (evidenceFailure) badges.unshift(`<span class="badge badge-evidence-error" title="${escapeAttr(evidenceFailureReason(evidenceFailure))}">MD 생성 차단</span>`);
  const domainLabel = {
    electrical: "전기적 요인",
    battery: "배터리 요인",
    mechanical: "기계적 요인",
    negligence: "부주의",
    intentional: "방화·고의",
    natural: "자연적 요인",
    undetermined: "원인"
  }[a.incident?.cause_domain];
  const certaintyLabel = {
    confirmed: "확정",
    suspected: "추정",
    under_investigation: "조사 중",
    unknown: "미상"
  }[a.incident?.cause_certainty];
  const causeBadge = domainLabel && certaintyLabel
    ? `${domainLabel} ${certaintyLabel}`
    : {
      unknown: "원인 미상 화재",
      electrical_suspected: "전기 원인 의심",
      electrical_confirmed: "전기 원인 확인"
    }[a.incident?.cause_status];
  if (a.incident?.incident_type === "fire" && causeBadge) badges.unshift(`<span class="badge badge-incident">${causeBadge}</span>`);
  if (isYonhapArticle(a)) badges.unshift('<span class="badge badge-yonhap">연합뉴스 우선</span>');
  if (isKescoPressArticle(a)) {
    const originLabel = a.origin.effectiveType === "kesco_republication" ? "보도자료 전재" : "보도자료 기반";
    const releaseTitle = a.origin.pressRelease?.title || "공사 보도자료";
    badges.unshift(`<span class="badge badge-press-origin" title="${escapeAttr(releaseTitle)}">${originLabel}</span>`);
  }
  if (isKescoPressIssue(issue)) badges.unshift('<span class="badge badge-press-origin">공사 보도자료 확산</span>');
  if (a.included) badges.push('<span class="badge badge-selected">브리핑 선정</span>');
  if (issue) {
    badges.unshift(`<span class="badge badge-same-issue">그룹 검토 <span class="review-stars">${starsText(issue.effectiveReviewStars)}</span> · ${issue.autoReviewRank || "-"}위</span>`);
  }
  if (a.topIssue && !issue) badges.push('<span class="badge badge-top-issue">Top 이슈</span>');
  if (a.manual) badges.push('<span class="badge badge-manual">직접 추가</span>');
  if (a.isDemo) badges.push('<span class="badge badge-watch">샘플</span>');
  if (a.stale) badges.push('<span class="badge badge-watch" title="이전 수집 실패로 최신 상태를 확인하지 못했습니다">최신 미확인</span>');
  const topIssueButton = issue
    ? `<button class="article-top-toggle media-top-toggle ${issue.selected ? "active" : ""}" data-action="top-issue" title="${issue.directCoverage ? "공사 직접 보도는 Top Issues에 선정할 수 없습니다" : "그룹을 Top 이슈로 태그"}" aria-label="그룹 Top 이슈 태그" aria-pressed="${String(!!issue.selected)}" ${state.status === "final" || issue.directCoverage ? "disabled" : ""}>${issue.selected ? "✓ TOP" : "+ TOP"}</button>`
    : `<button class="article-top-toggle ${a.topIssue ? "active" : ""}" data-action="article-top-issue" title="${a.directCoverage ? "공사 직접 보도는 Top Issues에 선정할 수 없습니다" : "개별 기사를 Top 이슈로 태그"}" aria-label="Top 이슈 태그" aria-pressed="${String(!!a.topIssue)}" ${state.status === "final" || a.directCoverage ? "disabled" : ""}>${a.topIssue ? "✓ TOP" : "+ TOP"}</button>`;
  const directCoverageButton = issue
    ? `<button class="article-direct-toggle ${issue.directCoverage ? "active" : ""}" data-action="direct-coverage" title="${issue.editorDirectCoverage == null ? "자동 판정 · 클릭하여 수동 해제" : "담당자 판정 · 클릭하여 전환"}" aria-label="공사 직접 보도 태그" aria-pressed="${String(!!issue.directCoverage)}" ${state.status === "final" ? "disabled" : ""}>${issue.directCoverage ? "공사보도 ✓" : "+ 공사보도"}</button>`
    : `<button class="article-direct-toggle ${a.directCoverage ? "active" : ""}" data-action="article-direct-coverage" title="${a.editorDirectCoverage == null ? "자동 판정 · 클릭하여 수동 해제" : "담당자 판정 · 클릭하여 전환"}" aria-label="공사 직접 보도 태그" aria-pressed="${String(!!a.directCoverage)}" ${state.status === "final" ? "disabled" : ""}>${a.directCoverage ? "공사보도 ✓" : "+ 공사보도"}</button>`;
  const effectiveDirectCoverage = !!(issue?.directCoverage || (!issue && a.directCoverage));
  const qualityById = new Map((issue?.evidenceArticles || []).map(item => [item.articleId, item]));
  const orderedRelatedMembers = issue && qualitySortedIssueIds.has(issue.id)
    ? [...relatedMembers].sort((left, right) => {
      const leftQuality = qualityById.get(left.article.id) || {};
      const rightQuality = qualityById.get(right.article.id) || {};
      return Number(rightQuality.contentQualityScore || 0) - Number(leftQuality.contentQualityScore || 0)
        || Number(rightQuality.cleanedCharacterCount || 0) - Number(leftQuality.cleanedCharacterCount || 0)
        || dateValue(right.article.pubDate) - dateValue(left.article.pubDate);
    })
    : [...relatedMembers].sort((left, right) => {
      const leftRepresentative = left.article.id === issue?.representativeArticleId ? 1 : 0;
      const rightRepresentative = right.article.id === issue?.representativeArticleId ? 1 : 0;
      return rightRepresentative - leftRepresentative;
    });
  const reextractingAll = issue && reextractingIssueIds.has(issue.id);
  const searchingRelated = searchingRelatedArticleIds.has(a.id);
  const relatedCount = relatedMembers.filter(member => member.article.id !== a.id).length;
  const relatedArticles = issue && relatedCount ? `<details class="related-articles" data-issue-id="${escapeAttr(issue.id)}" ${expandedIssueIds.has(issue.id) ? "open" : ""}>
    <summary>관련기사 ${relatedCount}건 <span class="related-articles-chevron" aria-hidden="true">›</span></summary>
    <div class="related-article-toolbar no-print">
      <button type="button" data-action="sort-related-quality" aria-pressed="${String(qualitySortedIssueIds.has(issue.id))}" class="${qualitySortedIssueIds.has(issue.id) ? "active" : ""}">본문 충실도순</button>
      <button type="button" data-action="reextract-all-bodies" aria-busy="${String(!!reextractingAll)}" ${state.status === "final" || reextractingAll ? "disabled" : ""}>${reextractingAll ? `전체 본문 추출 중… (${relatedMembers.length}건)` : "전체 본문 다시 추출"}</button>
    </div>
    ${issue.representativeEvidenceMissing ? '<div class="representative-missing"><strong>대표 근거 기사 미확보</strong><span>이 이슈에서 AI 분석에 사용할 수 있는 기사 본문을 확보하지 못했습니다. 본문을 다시 추출하거나 다른 기사를 추가해 주세요.</span></div>' : ""}
    ${issue.manualRepresentativeMissing ? '<div class="representative-missing"><strong>수동 대표기사 확인 필요</strong><span>기존 수동 대표기사를 현재 이슈에서 찾을 수 없습니다.</span></div>' : ""}
    <ul class="related-article-list">${orderedRelatedMembers.map(member => renderRelatedArticle(member.article, issue)).join("")}</ul>
  </details>` : "";
  const reviewControl = issue ? `<select class="review-star-select" data-action="review-stars" data-issue-id="${escapeAttr(issue.id)}" aria-label="그룹 검토별점" ${state.status === "final" ? "disabled" : ""}>
    <option value="auto" ${issue.editorReviewStars == null ? "selected" : ""}>자동 ${starsText(issue.autoReviewStars)}</option>
    ${[5,4,3,2,1].map(stars => `<option value="${stars}" ${issue.editorReviewStars === stars ? "selected" : ""}>${starsText(stars)}</option>`).join("")}
  </select>` : "";
  return `<article class="article-card ${issue ? "grouped-article-card" : ""} ${a.included ? "included" : ""} ${issue?.selected ? "top-tagged" : ""}" data-id="${escapeAttr(a.id)}" ${issue ? `data-issue-id="${escapeAttr(issue.id)}"` : ""}>
    <input class="include-check" type="checkbox" aria-label="브리핑 선정" title="${effectiveDirectCoverage ? "선정하면 공사 직접 보도 태그를 수동 해제하고 브리핑 기사로 반영합니다" : "브리핑 선정"}" data-action="include" ${a.included ? "checked" : ""} ${state.status === "final" ? "disabled" : ""}>
    <div class="article-main">
      <div class="article-badges"><span class="category-label" style="color:${CATEGORY_COLORS[a.category] || "#326c9c"}">${escapeHtml(category)}</span>${badges.join("")}</div>
      ${titleEl}
      <div class="article-meta"><strong>${escapeHtml(a.source || "출처 미상")}</strong><span>${formatDateTime(a.pubDate)}</span><span>${escapeHtml(relevance.reasons.join(" · "))}</span><span>${escapeHtml((a.matchedKeywords || []).slice(0,4).join(" · ") || "키워드 자동 분류")}</span></div>
      ${a.description ? `<p class="article-desc">${escapeHtml(a.description)}</p>` : ""}
      <input class="article-note" data-action="note" value="${escapeAttr(a.note || "")}" aria-label="기사 메모" placeholder="보고 메모 추가 (인쇄에는 포함되지 않음)" ${state.status === "final" ? "disabled" : ""}>
    </div>
    <div class="article-actions">
      ${reviewControl}
      <button class="related-search-btn" data-action="search-related" aria-busy="${String(searchingRelated)}" title="제목 핵심어를 여러 조합으로 Google·네이버에서 검색해 관련기사를 최대 10건 찾습니다" ${state.status === "final" || searchingRelated ? "disabled" : ""}>${searchingRelated ? "검색 중…" : "관련기사 검색"}</button>
      ${directCoverageButton}
      ${topIssueButton}
      <button class="small-icon ${a.starred ? "active" : ""}" data-action="star" title="중요 기사" aria-label="중요 기사" ${state.status === "final" ? "disabled" : ""}>${ICONS.star}</button>
      <button class="small-icon" data-action="delete" title="기사 삭제" aria-label="기사 삭제" ${state.status === "final" ? "disabled" : ""}>${ICONS.trash}</button>
    </div>
    ${relatedArticles}
  </article>`;
}

function renderRelatedArticle(a, issue) {
  const quality = (issue.evidenceArticles || []).find(item => item.articleId === a.id) || {};
  const evidenceFailure = evidenceFailureFor(a.id, issue.id);
  const href = safeUrl(a.url);
  const titleEl = href
    ? `<a class="related-article-title" href="${escapeAttr(href)}" target="_blank" rel="noopener noreferrer">${escapeHtml(a.title)}</a>`
    : `<span class="related-article-title">${escapeHtml(a.title)}</span>`;
  const directCoverage = !!(issue.directCoverage || a.directCoverage);
  const roleLabel = { representative: "현재 대표", supplemental: "보조근거", excluded: "분석 제외", related: "관련기사" }[quality.role] || "관련기사";
  const statusLabel = { success_full: "전문 확보", success_summary: "유효 요약", failed: "본문 추출 실패", not_attempted: "추출 전" }[quality.extractionStatus] || "추출 전";
  const gradeLabel = { excellent: "본문 충실도 우수", good: "본문 충실도 양호", limited: "본문 충실도 제한", unavailable: "본문 충실도 부족" }[quality.qualityGrade] || "본문 충실도 부족";
  const previewKey = `${issue.id}:${a.id}`;
  const previewOpen = quality.role === "representative"
    ? !collapsedRepresentativePreviewKeys.has(previewKey)
    : expandedPreviewKeys.has(previewKey);
  const validationErrors = quality.validationErrors || [];
  const validationText = validationErrors.map(item => `${EVIDENCE_ERROR_LABELS[item] || item}: ${EVIDENCE_ERROR_MESSAGES[item] || item}`);
  const disabledReason = quality.analysisEligible
    ? ""
    : (validationText.length ? validationText : (quality.qualityReasons || ["유효한 기사 본문을 확보하지 못했습니다."])).join(" · ");
  const sourceVerified = !!quality.sourceDomain && !validationErrors.some(item => ["publisher_identity_mismatch", "canonical_url_unresolved"].includes(item));
  return `<li class="related-article-row related-role-${escapeAttr(quality.role || "related")}" data-id="${escapeAttr(a.id)}" data-issue-id="${escapeAttr(issue.id)}">
    <input class="include-check related-include-check" type="checkbox" data-action="include" aria-label="브리핑 선정" title="${directCoverage ? "선정하면 공사 직접 보도 태그를 수동 해제하고 브리핑 기사로 반영합니다" : "브리핑 선정"}" ${a.included ? "checked" : ""} ${state.status === "final" ? "disabled" : ""}>
    <div class="related-article-content">
      <div class="related-article-heading">${titleEl}<span class="related-article-meta"><strong>${escapeHtml(quality.normalizedSource || a.source || "출처 미상")}</strong> · ${formatDateTime(a.pubDate)}</span></div>
      <div class="related-quality-badges">${evidenceFailure ? `<span class="badge badge-evidence-error" title="${escapeAttr(evidenceFailureReason(evidenceFailure))}">MD 생성 차단</span>` : ""}<span class="evidence-role role-${escapeAttr(quality.role || "related")}">${roleLabel}</span><span class="quality-status status-${escapeAttr(quality.extractionStatus || "not_attempted")}">${statusLabel}</span><span class="quality-grade grade-${escapeAttr(quality.qualityGrade || "unavailable")}">${gradeLabel} ${Number(quality.contentQualityScore || 0)}</span></div>
      <div class="related-quality-meta">최초 수집 언론사 ${escapeHtml(quality.rawSource || a.source || "미확인")} · 실제 원문 도메인 ${escapeHtml(quality.sourceDomain || "미확인")} · 정제 ${Number(quality.cleanedCharacterCount || 0).toLocaleString("ko-KR")}자 · ${quality.lastExtractedAt ? formatDateTime(quality.lastExtractedAt) : "추출 전"}</div>
      <div class="source-validation ${sourceVerified ? "verified" : "invalid"}">${sourceVerified ? "출처 확인 완료" : (quality.lastExtractedAt ? "출처 확인 필요" : "출처 확인 전")}${quality.normalizationReason && quality.normalizationReason !== "raw_source" ? ` · 언론사명 정상화(${escapeHtml(quality.normalizationReason)})` : ""}</div>
      ${validationErrors.length ? `<div class="evidence-validation-errors"><strong>대표기사 지정 불가</strong><span>${escapeHtml(validationText.join(" · "))}</span></div>` : ""}
      <div class="related-quality-meta">${escapeHtml((quality.qualityReasons || []).join(" · ") || "품질 평가 전")}</div>
      ${previewOpen ? `<div class="article-body-preview"><dl><div><dt>정제 전</dt><dd>${Number(quality.rawCharacterCount || 0).toLocaleString("ko-KR")}자</dd></div><div><dt>정제 후</dt><dd>${Number(quality.cleanedCharacterCount || 0).toLocaleString("ko-KR")}자</dd></div><div><dt>추출 시각</dt><dd>${quality.lastExtractedAt ? formatDateTime(quality.lastExtractedAt) : "없음"}</dd></div></dl><p>${escapeHtml(quality.cleanedText || "확인할 정제 본문이 없습니다.")}</p></div>` : ""}
    </div>
    <div class="related-evidence-actions no-print">
      <button data-action="preview-body">${previewOpen ? "미리보기 닫기" : "본문 미리보기"}</button>
      ${href ? `<a href="${escapeAttr(href)}" target="_blank" rel="noopener noreferrer">원문 열기</a>` : ""}
      <button data-action="reextract-body" ${state.status === "final" ? "disabled" : ""}>본문 다시 추출</button>
      <button data-action="set-representative" title="${escapeAttr(disabledReason)}" ${state.status === "final" || !quality.analysisEligible || quality.role === "representative" ? "disabled" : ""}>대표기사로 지정</button>
      <button data-action="toggle-supplemental" title="${escapeAttr(disabledReason)}" ${state.status === "final" || (!quality.analysisEligible && quality.role !== "supplemental") || quality.role === "representative" ? "disabled" : ""}>${quality.role === "supplemental" ? "보조근거 해제" : "보조근거로 지정"}</button>
      <button data-action="toggle-analysis-excluded" ${state.status === "final" ? "disabled" : ""}>${quality.role === "excluded" ? "분석 제외 해제" : "분석 제외"}</button>
      <button class="related-remove-btn" data-action="remove-related" title="이 기사를 현재 관련기사 묶음에서 제거" ${state.status === "final" ? "disabled" : ""}>묶음에서 제거</button>
    </div>
  </li>`;
}

export function focusRelatedEvidence(issueId, articleId) {
  expandedIssueIds.add(issueId);
  setFilters({ ...filters, text: "", category: "all", risk: "all", selection: "all" });
  els.articleSearch.value = "";
  els.categoryFilter.value = "all";
  els.riskFilter.value = "all";
  els.selectionFilter.value = "all";
  renderAll();
  const reveal = () => {
    const card = [...document.querySelectorAll(".article-card")]
      .find(item => item.dataset.issueId === issueId);
    const details = card?.querySelector(".related-articles");
    if (details) details.open = true;
    const row = [...document.querySelectorAll(".related-article-row")]
      .find(item => item.dataset.issueId === issueId && item.dataset.id === articleId);
    const target = row || card;
    target?.scrollIntoView({ behavior: "auto", block: "center" });
    row?.classList.add("evidence-focus");
  };
  requestAnimationFrame(() => {
    reveal();
    window.setTimeout(reveal, 100);
  });
}

function rememberExpandedIssues() {
  expandedIssueIds.clear();
  els.articleList?.querySelectorAll(".related-articles[open]").forEach(details => {
    expandedIssueIds.add(details.dataset.issueId);
  });
}

function renderMediaGroups(items) {
  if (!state.issues.length) {
    const general = items.filter(article => !isKescoPressArticle(article)).map(article => renderArticleCard(article)).join("");
    const press = items.filter(isKescoPressArticle).map(article => renderArticleCard(article)).join("");
    return press
      ? `${general}<div class="coverage-section-heading"><strong>공사 보도자료 확산</strong><span>공사 원문에서 파생된 기사를 보도자료별 한 묶음으로 표시합니다.</span></div>${press}`
      : general;
  }
  const itemById = new Map(items.map((article, index) => [article.id, { article, index }]));
  const articleById = new Map(state.articles.map(article => [article.id, article]));
  const issueByArticle = primaryIssueByArticle(state.issues);
  const groupedIds = new Set();
  const groups = state.issues.map(issue => {
    const members = issue.articleIds
      .filter(articleId => issueByArticle.get(articleId)?.id === issue.id)
      .map(articleId => itemById.get(articleId))
      .filter(Boolean)
      .sort((left, right) => left.index - right.index);
    members.forEach(member => groupedIds.add(member.article.id));
    // 카드의 관련기사 수와 펼침 목록은 현재 화면 필터가 아니라 이슈 전체 membership을 따른다.
    const managementMembers = issue.articleIds
      .filter(articleId => issueByArticle.get(articleId)?.id === issue.id)
      .map(articleId => articleById.get(articleId))
      .filter(Boolean)
      .map(article => ({ article }));
    return { issue, members, managementMembers, position: members[0]?.index };
  }).filter(group => group.members.length);
  const entries = groups.map(({ issue, members, managementMembers, position }) => {
    const representative = members.find(member => member.article.id === issue.representativeArticleId) || members[0];
    return { position, press: isKescoPressIssue(issue), html: renderArticleCard(representative.article, issue, managementMembers) };
  });
  items.forEach((article, index) => {
    if (!groupedIds.has(article.id)) entries.push({ position: index, press: isKescoPressArticle(article), html: renderArticleCard(article) });
  });
  const ordered = entries.sort((left, right) => left.position - right.position);
  const general = ordered.filter(entry => !entry.press).map(entry => entry.html).join("");
  const press = ordered.filter(entry => entry.press).map(entry => entry.html).join("");
  if (!press) return general;
  return `${general}<div class="coverage-section-heading"><strong>공사 보도자료 확산</strong><span>공사 원문에서 파생된 기사를 보도자료별 한 묶음으로 표시합니다.</span></div>${press}`;
}

export function renderArticles() {
  rememberExpandedIssues();
  const currentIds = new Set(state.articles.map(article => article.id));
  for (const articleId of manualGroupSelection) {
    if (!currentIds.has(articleId)) manualGroupSelection.delete(articleId);
  }
  updateManualGroupControls();
  const selectedCount = state.articles.filter(article => article.included).length;
  const selectedOnlyActive = filters.selection === "selected";
  const issueByArticle = primaryIssueByArticle(state.issues);
  els.selectedOnlyCount.textContent = selectedCount;
  els.selectedOnlyBtn.classList.toggle("active", selectedOnlyActive);
  els.selectedOnlyBtn.setAttribute("aria-pressed", String(selectedOnlyActive));
  els.selectedOnlyBtn.title = selectedOnlyActive ? "전체 기사 보기" : `선택한 기사 ${selectedCount}건만 보기`;
  let items = state.articles.filter(a => {
    const issue = issueByArticle.get(a.id);
    const hay = `${a.title} ${a.source} ${a.description || ""} ${(a.matchedKeywords || []).join(" ")} ${issue?.effectiveTitle || ""}`.toLowerCase();
    const selectionMatch = filters.selection === "all" || (filters.selection === "selected" && a.included) || (filters.selection === "starred" && a.starred) || (filters.selection === "unselected" && !a.included);
    const reviewMatch = filters.risk === "all" || Number(filters.risk) === Number(issue?.effectiveReviewStars);
    return (!filters.text || hay.includes(filters.text)) && (filters.category === "all" || a.category === filters.category) && reviewMatch && selectionMatch;
  });
  if (filters.sort === "relevance") items.sort(relevanceSort);
  else if (filters.sort === "collection") {
    const counts = relatedArticleCounts();
    items.sort((a, b) => collectionOrderSort(a, b, counts));
  }
  else if (filters.sort === "newest") items.sort((a,b) => dateValue(b.pubDate)-dateValue(a.pubDate));
  else if (filters.sort === "source") items.sort((a,b) => (a.source || "").localeCompare(b.source || "", "ko"));
  else if (filters.sort === "review") {
    items.sort((a, b) => {
      const left = issueByArticle.get(a.id); const right = issueByArticle.get(b.id);
      return (right?.effectiveReviewStars || 0) - (left?.effectiveReviewStars || 0)
        || (left?.autoReviewRank || 999999) - (right?.autoReviewRank || 999999)
        || relevanceSort(a, b);
    });
  }
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

  els.articleList.innerHTML = renderMediaGroups(items);
  updateManualGroupControls();
}

export async function handleArticleChange(e) {
  if (state.status === "final") return;
  if (e.target.dataset.action === "review-stars") {
    const issue = state.issues.find(candidate => candidate.id === e.target.dataset.issueId);
    if (issue) updateReviewStars(issue, e.target.value);
    return;
  }
  const item = e.target.closest("[data-id]"); if (!item) return;
  const article = state.articles.find(a => a.id === item.dataset.id); if (!article) return;
  if (e.target.dataset.action === "include") {
    const issue = primaryIssueByArticle(state.issues).get(article.id);
    const selecting = e.target.checked;
    const directCoverage = !!(issue?.directCoverage || (!issue && article.directCoverage));
    article.included = selecting;
    const patch = { selected: selecting };
    if (selecting && directCoverage) {
      patch.directCoverage = false;
      article.directCoverage = false;
      article.editorDirectCoverage = false;
      if (issue) {
        issue.directCoverage = false;
        issue.editorDirectCoverage = false;
      }
    }
    afterArticleMutation();
    const saved = await patchArticle(article.id, patch);
    if (!saved) {
      setState(await loadDailyState(state.date));
      renderAll();
      return;
    }
    showToast(
      selecting
        ? directCoverage
          ? "공사 직접 보도 태그를 수동 해제하고 브리핑 기사로 선정했습니다."
          : "브리핑 기사로 선정했습니다."
        : "브리핑 선정을 해제했습니다.",
      selecting ? "success" : "",
    );
  }
}

async function searchRelatedArticles(articleId) {
  if (searchingRelatedArticleIds.has(articleId)) return;
  searchingRelatedArticleIds.add(articleId);
  renderArticles();
  showToast("제목 핵심어를 여러 조합으로 Google·네이버에서 검색하고 있습니다.");
  try {
    await flushArticleChanges();
    const result = await api.searchRelatedArticles(state.date, articleId, state.revision);
    state.revision = result.data.revision;
    setState(await loadDailyState(state.date));
    const count = Number(result.data.foundCount || 0);
    const added = Number(result.data.addedCount || 0);
    if (result.data.issueId) expandedIssueIds.add(result.data.issueId);
    showToast(
      count
        ? `관련기사 ${count}건을 찾고 ${added}건을 현재 묶음에 추가했습니다.`
        : "출처 도메인이 확인되는 추가 관련기사를 찾지 못했습니다.",
      count ? "success" : "",
    );
  } catch (error) {
    if (error.code === "BRIEFING_REVISION_CONFLICT") {
      setState(await loadDailyState(state.date));
    }
    showToast(`관련기사 검색 실패: ${friendlyError(error)}`, "error");
  } finally {
    searchingRelatedArticleIds.delete(articleId);
    renderAll();
  }
}

async function updateReviewStars(issue, value) {
  const previous = issue.editorReviewStars;
  issue.editorReviewStars = value === "auto" ? null : Number(value);
  issue.effectiveReviewStars = issue.editorReviewStars ?? issue.autoReviewStars;
  renderAll();
  try {
    const result = await api.patchBriefingIssue(state.date, issue.id, state.revision, { editorReviewStars: issue.editorReviewStars });
    state.revision = result.data.revision;
    showToast(issue.editorReviewStars == null ? "자동 검토별점으로 되돌렸습니다." : `담당자 검토별점을 ${issue.editorReviewStars}점으로 저장했습니다.`, "success");
  } catch (error) {
    issue.editorReviewStars = previous;
    issue.effectiveReviewStars = previous ?? issue.autoReviewStars;
    if (error.code === "BRIEFING_REVISION_CONFLICT") setState(await loadDailyState(state.date));
    showToast(`검토별점 저장 실패: ${friendlyError(error)}`, "error");
    renderAll();
  }
}

function updateManualGroupControls() {
  if (!els.manualGroupBtn || !els.manualGroupModeBtn) return;
  const count = manualGroupSelection.size;
  els.manualGroupCount.textContent = count;
  els.manualGroupUnitCount.textContent = manualGroupSelectedKeys.size;
  els.manualGroupBtn.disabled = manualGroupSelectedKeys.size < 2 || count < 2 || state.status === "final";
  els.manualGroupModeBtn.disabled = state.status === "final";
}

function buildManualGroupPickerEntries() {
  const articleById = new Map(state.articles.map(article => [article.id, article]));
  const groupedArticleIds = new Set();
  const entries = [];
  state.issues.forEach(issue => {
    const members = issue.articleIds.map(articleId => articleById.get(articleId)).filter(Boolean);
    if (members.length < 2) return;
    members.forEach(article => groupedArticleIds.add(article.id));
    const sources = [...new Set(members.map(article => article.source || "출처 미상"))];
    entries.push({
      key: `issue:${issue.id}`,
      articleIds: members.map(article => article.id),
      title: issue.effectiveTitle || members[0].title,
      detail: `기존 묶음 · 기사 ${members.length}건 · ${sources.slice(0, 3).join(" · ")}${sources.length > 3 ? ` 외 ${sources.length - 3}개 매체` : ""}`,
      searchText: members.map(article => `${article.title} ${article.source || ""}`).join(" "),
      grouped: true,
    });
  });
  state.articles.forEach(article => {
    if (groupedArticleIds.has(article.id)) return;
    entries.push({
      key: `article:${article.id}`,
      articleIds: [article.id],
      title: article.title,
      detail: `${article.source || "출처 미상"} · ${formatDateTime(article.pubDate)}`,
      searchText: `${article.title} ${article.source || ""}`,
      grouped: false,
    });
  });
  return entries;
}

function syncManualGroupArticleSelection() {
  manualGroupSelection.clear();
  manualGroupSelectedKeys.forEach(key => {
    manualGroupPickerEntries.get(key)?.articleIds.forEach(articleId => manualGroupSelection.add(articleId));
  });
}

function renderManualGroupPicker() {
  const query = manualGroupSearchText.toLowerCase();
  const entries = buildManualGroupPickerEntries();
  manualGroupPickerEntries = new Map(entries.map(entry => [entry.key, entry]));
  for (const key of manualGroupSelectedKeys) {
    if (!manualGroupPickerEntries.has(key)) manualGroupSelectedKeys.delete(key);
  }
  syncManualGroupArticleSelection();
  const visibleEntries = entries.filter(entry => !query || `${entry.title} ${entry.detail} ${entry.searchText}`.toLowerCase().includes(query));
  els.manualGroupList.innerHTML = visibleEntries.length ? visibleEntries.map(entry => `<label class="manual-group-item ${entry.grouped ? "is-group" : ""}">
    <input type="checkbox" data-action="group-picker-select" data-selection-key="${escapeAttr(entry.key)}" ${manualGroupSelectedKeys.has(entry.key) ? "checked" : ""}>
    <span>${entry.grouped ? '<em class="manual-group-type">관련기사 묶음</em>' : ""}<strong>${escapeHtml(entry.title)}</strong><small>${escapeHtml(entry.detail)}</small></span>
  </label>`).join("") : '<div class="manual-group-empty">검색 결과가 없습니다.</div>';
  updateManualGroupControls();
}

export function openManualGroupPicker() {
  if (state.status === "final") return;
  manualGroupSelection.clear();
  manualGroupSelectedKeys.clear();
  manualGroupSearchText = "";
  els.manualGroupSearch.value = "";
  renderManualGroupPicker();
  els.manualGroupOverlay.classList.add("open");
  document.body.style.overflow = "hidden";
}

export function closeManualGroupPicker() {
  manualGroupSelection.clear();
  manualGroupSelectedKeys.clear();
  els.manualGroupOverlay.classList.remove("open");
  if (!document.querySelector(".overlay.open")) document.body.style.overflow = "";
  updateManualGroupControls();
}

export function handleManualGroupPickerChange(e) {
  if (e.target.dataset.action !== "group-picker-select") return;
  const selectionKey = e.target.dataset.selectionKey;
  if (e.target.checked) manualGroupSelectedKeys.add(selectionKey);
  else manualGroupSelectedKeys.delete(selectionKey);
  syncManualGroupArticleSelection();
  updateManualGroupControls();
}

export function handleManualGroupSearch(e) {
  manualGroupSearchText = e.target.value.trim();
  renderManualGroupPicker();
}

export async function createManualGroup() {
  if (manualGroupSelectedKeys.size < 2 || manualGroupSelection.size < 2 || state.status === "final") return;
  const articleIds = [...manualGroupSelection];
  els.manualGroupBtn.disabled = true;
  try {
    const result = await api.createManualIssueGroup(state.date, articleIds, state.revision);
    state.revision = result.data.revision;
    const issuesResult = await api.listIssues(state.date);
    state.issues = issuesResult.data.issues || [];
    manualGroupSelection.clear();
    closeManualGroupPicker();
    renderAll();
    showToast(`${articleIds.length}건을 관련기사로 묶었습니다.`, "success");
  } catch (error) {
    if (error.code === "BRIEFING_REVISION_CONFLICT") {
      setState(await loadDailyState(state.date));
      closeManualGroupPicker();
      renderAll();
    }
    showToast(`관련기사 묶기 실패: ${friendlyError(error)}`, "error");
    updateManualGroupControls();
  }
}

export function handleArticleInput(e) {
  if (state.status === "final") return;
  if (e.target.dataset.action !== "note") return;
  const item = e.target.closest("[data-id]");
  const article = state.articles.find(a => a.id === item?.dataset.id);
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
    setFilters({ text: "", category: "all", risk: "all", selection: "all", sort: "review" });
    els.articleSearch.value = ""; els.categoryFilter.value = "all"; els.riskFilter.value = "all"; els.selectionFilter.value = "all"; els.sortOrder.value = "review"; renderArticles(); return;
  }
  if (!action) return;
  const evidenceRow = e.target.closest("[data-issue-id][data-id]");
  if (action === "preview-body" && evidenceRow) {
    const key = `${evidenceRow.dataset.issueId}:${evidenceRow.dataset.id}`;
    const issue = state.issues.find(item => item.id === evidenceRow.dataset.issueId);
    const quality = issue?.evidenceArticles?.find(item => item.articleId === evidenceRow.dataset.id);
    if (quality?.role === "representative") {
      if (collapsedRepresentativePreviewKeys.has(key)) collapsedRepresentativePreviewKeys.delete(key);
      else collapsedRepresentativePreviewKeys.add(key);
    } else if (expandedPreviewKeys.has(key)) expandedPreviewKeys.delete(key);
    else expandedPreviewKeys.add(key);
    renderArticles();
    return;
  }
  const relatedDetails = e.target.closest(".related-articles[data-issue-id]");
  if (action === "sort-related-quality" && relatedDetails) {
    const issueId = relatedDetails.dataset.issueId;
    if (qualitySortedIssueIds.has(issueId)) qualitySortedIssueIds.delete(issueId);
    else qualitySortedIssueIds.add(issueId);
    renderArticles();
    return;
  }
  if (action === "reextract-all-bodies" && relatedDetails) {
    if (state.status !== "final") reextractAllIssueBodies(relatedDetails.dataset.issueId);
    return;
  }
  if (state.status === "final") return;
  if (action === "search-related") {
    const card = e.target.closest(".article-card[data-id]");
    if (card) searchRelatedArticles(card.dataset.id);
    return;
  }
  if (evidenceRow && ["reextract-body", "set-representative", "toggle-supplemental", "toggle-analysis-excluded"].includes(action)) {
    handleEvidenceAction(action, evidenceRow.dataset.issueId, evidenceRow.dataset.id);
    return;
  }
  if (action === "top-issue") {
    const group = e.target.closest("[data-issue-id]");
    const issue = state.issues.find(item => item.id === group?.dataset.issueId);
    if (!issue) return;
    if (!issue.selected && topIssueTagCount() >= MAX_TOP_ISSUES) {
      showToast(`Top Issues는 최대 ${MAX_TOP_ISSUES}개까지 태그할 수 있습니다.`, "error");
      return;
    }
    toggleTopIssue(issue, group.dataset.id);
    return;
  }
  if (action === "direct-coverage") {
    const group = e.target.closest("[data-issue-id]");
    const issue = state.issues.find(item => item.id === group?.dataset.issueId);
    if (issue) toggleDirectCoverage(issue);
    return;
  }
  if (action === "remove-related") {
    const row = e.target.closest("[data-issue-id][data-id]");
    if (row) removeRelatedArticle(row.dataset.issueId, row.dataset.id);
    return;
  }
  const item = e.target.closest("[data-id]");
  const article = state.articles.find(a => a.id === item?.dataset.id); if (!article) return;
  if (action === "article-direct-coverage") {
    toggleArticleDirectCoverage(article);
    return;
  }
  if (action === "article-top-issue") {
    if (!article.topIssue && topIssueTagCount() >= MAX_TOP_ISSUES) {
      showToast(`Top Issues는 그룹과 개별 기사를 합쳐 최대 ${MAX_TOP_ISSUES}개까지 태그할 수 있습니다.`, "error");
      return;
    }
    toggleArticleTopIssue(article);
    return;
  }
  if (action === "star") { article.starred = !article.starred; afterArticleMutation(); trackArticlePatch(article.id, { starred: article.starred }); }
  if (action === "delete") {
    state.articles = state.articles.filter(a => a.id !== article.id);
    afterArticleMutation();
    trackArticlePatch(article.id, { dismissed: true });
    showToast("기사를 브리핑에서 삭제했습니다(휴지통으로 이동, 메모·중요 표시는 보존됩니다).");
  }
}

async function reextractAllIssueBodies(issueId) {
  if (reextractingIssueIds.has(issueId)) return;
  const issue = state.issues.find(item => item.id === issueId);
  if (!issue) return;
  reextractingIssueIds.add(issueId);
  renderArticles();
  showToast(`관련기사 ${issue.articleIds?.length || 0}건의 본문을 동시에 다시 추출하고 충실도를 평가합니다.`);
  try {
    const result = await api.reextractIssueArticles(issueId);
    const issuesResult = await api.listIssues(state.date);
    state.issues = issuesResult.data.issues || [];
    const failedCount = Number(result.data.failedCount || 0);
    showToast(
      failedCount
        ? `전체 본문 추출 완료 · 성공 ${result.data.succeededCount}건 · 실패 ${failedCount}건`
        : `전체 본문 추출과 충실도 평가 ${result.data.succeededCount}건을 완료했습니다.`,
      failedCount ? "" : "success",
    );
  } catch (error) {
    showToast(`전체 본문 재추출 실패: ${friendlyError(error)}`, "error");
  } finally {
    reextractingIssueIds.delete(issueId);
    renderAll();
  }
}

async function handleEvidenceAction(action, issueId, articleId) {
  const issue = state.issues.find(item => item.id === issueId);
  if (!issue) return;
  if (action === "reextract-body") {
    showToast("기사 본문을 다시 추출하고 품질을 평가하고 있습니다.");
    try {
      const result = await api.reextractArticle(articleId);
      const issuesResult = await api.listIssues(state.date);
      state.issues = issuesResult.data.issues || [];
      renderAll();
      showToast(
        result.data.analysisEligible
          ? `본문 재추출 완료 · AI 분석 적합도 ${result.data.contentQualityScore}`
          : `본문 재추출 완료 · 분석 제한 (${(result.data.qualityReasons || []).join(" · ")})`,
        result.data.analysisEligible ? "success" : "",
      );
    } catch (error) {
      showToast(`본문 재추출 실패: ${friendlyError(error)}`, "error");
    }
    return;
  }
  let representativeArticleId = issue.manualRepresentativeArticleId || null;
  let supplementalArticleIds = [...(issue.manualSupplementalArticleIds || [])];
  let excludedArticleIds = [...(issue.manualExcludedArticleIds || [])];
  if (action === "set-representative") {
    representativeArticleId = articleId;
    supplementalArticleIds = supplementalArticleIds.filter(id => id !== articleId);
    excludedArticleIds = excludedArticleIds.filter(id => id !== articleId);
  } else if (action === "toggle-supplemental") {
    if (supplementalArticleIds.includes(articleId)) {
      supplementalArticleIds = supplementalArticleIds.filter(id => id !== articleId);
    } else {
      if (supplementalArticleIds.length >= 2) {
        showToast("보조근거는 최대 2건입니다. 기존 보조근거를 먼저 해제해 주세요.", "error");
        return;
      }
      supplementalArticleIds.push(articleId);
      excludedArticleIds = excludedArticleIds.filter(id => id !== articleId);
    }
  } else if (action === "toggle-analysis-excluded") {
    if (excludedArticleIds.includes(articleId)) {
      excludedArticleIds = excludedArticleIds.filter(id => id !== articleId);
    } else {
      excludedArticleIds.push(articleId);
      supplementalArticleIds = supplementalArticleIds.filter(id => id !== articleId);
      if (representativeArticleId === articleId || issue.representativeArticleId === articleId) {
        representativeArticleId = null;
      }
    }
  }
  try {
    const result = await api.patchIssueEvidence(issueId, {
      expectedRevision: issue.evidenceRevision || 0,
      representativeArticleId,
      supplementalArticleIds,
      excludedArticleIds,
    });
    const updated = result.data;
    Object.assign(issue, updated, { evidenceArticles: updated.articles || [] });
    renderAll();
    showToast("관련기사 분석 근거 구성을 저장했습니다.", "success");
  } catch (error) {
    if (error.code === "ISSUE_EVIDENCE_REVISION_CONFLICT") {
      const issuesResult = await api.listIssues(state.date);
      state.issues = issuesResult.data.issues || [];
      renderAll();
    }
    showToast(`분석 근거 저장 실패: ${friendlyError(error)}`, "error");
  }
}

export function handleTopIssuesClick(e) {
  const action = e.target.closest("[data-action]")?.dataset.action;
  if (state.status === "final") return;
  if (action === "move-top-issue") {
    moveTopIssue(e.target.closest("[data-action='move-top-issue']"));
    return;
  }
  if (action !== "remove-top-issue") return;
  const button = e.target.closest("[data-action='remove-top-issue']");
  const issue = state.issues.find(item => item.id === button?.dataset.issueId);
  if (issue) {
    toggleTopIssue(issue);
    return;
  }
  const article = state.articles.find(item => item.id === button?.dataset.articleId);
  if (article?.topIssue) toggleArticleTopIssue(article);
}

async function moveTopIssue(button) {
  const entries = getTopIssueEntries();
  const currentIndex = entries.findIndex(entry =>
    entry.kind === button?.dataset.topKind && entry.item.id === button?.dataset.topId,
  );
  const offset = button?.dataset.direction === "up" ? -1 : 1;
  const targetIndex = currentIndex + offset;
  if (currentIndex < 0 || targetIndex < 0 || targetIndex >= entries.length) return;
  [entries[currentIndex], entries[targetIndex]] = [entries[targetIndex], entries[currentIndex]];
  entries.forEach((entry, index) => { entry.item.sortOrder = index; });
  renderAll();
  try {
    await flushArticleChanges();
    for (const [sortOrder, entry] of entries.entries()) {
      const result = entry.kind === "issue"
        ? await api.patchBriefingIssue(state.date, entry.item.id, state.revision, { sortOrder })
        : await api.patchBriefingArticle(state.date, entry.item.id, state.revision, { sortOrder });
      state.revision = result.data.revision;
    }
    showToast("탑이슈 배치 순서를 저장했습니다.", "success");
  } catch (error) {
    if (error.code === "BRIEFING_REVISION_CONFLICT") {
      showToast("다른 화면에서 변경 사항이 있어 최신 내용을 다시 불러옵니다.", "error");
    } else {
      showToast(`탑이슈 순서 저장 실패: ${friendlyError(error)}`, "error");
    }
    setState(await loadDailyState(state.date));
    renderAll();
  }
}

async function removeRelatedArticle(issueId, articleId) {
  const issue = state.issues.find(item => item.id === issueId);
  const article = state.articles.find(item => item.id === articleId);
  if (!issue || !article || !issue.articleIds.includes(articleId)) return;
  try {
    await flushArticleChanges();
    const result = await api.removeIssueArticle(state.date, issueId, articleId, state.revision);
    state.revision = result.data.revision;
    setState(await loadDailyState(state.date));
    renderAll();
    showToast("기사를 현재 관련기사 묶음에서 제거했습니다. 기사 자체와 선정·메모 상태는 유지됩니다.", "success");
  } catch (error) {
    if (error.code === "BRIEFING_REVISION_CONFLICT") setState(await loadDailyState(state.date));
    showToast(`관련기사 제거 실패: ${friendlyError(error)}`, "error");
    renderAll();
  }
}

async function toggleArticleTopIssue(article) {
  const topIssue = !article.topIssue;
  const previousIncluded = article.included;
  article.topIssue = topIssue;
  if (topIssue) article.included = true;
  renderAll();
  const saved = await patchArticle(article.id, { topIssue });
  if (!saved) {
    article.topIssue = !topIssue;
    article.included = previousIncluded;
    renderAll();
    return;
  }
  showToast(topIssue ? "개별 기사를 Top 이슈로 태그했습니다." : "개별 기사 Top 이슈 태그를 해제했습니다.", topIssue ? "success" : "");
}

async function toggleArticleDirectCoverage(article) {
  const directCoverage = !article.directCoverage;
  const previous = {
    directCoverage: article.directCoverage,
    editorDirectCoverage: article.editorDirectCoverage,
    included: article.included,
    topIssue: article.topIssue,
  };
  article.directCoverage = directCoverage;
  article.editorDirectCoverage = directCoverage;
  if (directCoverage) {
    article.included = false;
    article.topIssue = false;
  }
  renderAll();
  const saved = await patchArticle(article.id, { directCoverage });
  if (!saved) {
    Object.assign(article, previous);
    renderAll();
    return;
  }
  showToast(
    directCoverage
      ? "공사 직접 보도로 태그하고 일반 브리핑에서 제외했습니다."
      : "공사 직접 보도 태그를 해제했습니다.",
    "success",
  );
}

async function toggleTopIssue(issue, articleId) {
  const selected = !issue.selected;
  const article = state.articles.find(item => item.id === articleId);
  const previousIncluded = article?.included;
  issue.selected = selected;
  if (selected && article) article.included = true;
  renderAll();
  try {
    const result = await api.patchBriefingIssue(
      state.date,
      issue.id,
      state.revision,
      { selected, articleId },
    );
    state.revision = result.data.revision;
    showToast(selected ? "Top 이슈로 태그했습니다." : "Top 이슈 태그를 해제했습니다.", selected ? "success" : "");
  } catch (error) {
    issue.selected = !selected;
    if (article) article.included = previousIncluded;
    if (error.code === "BRIEFING_REVISION_CONFLICT") {
      showToast("다른 화면에서 변경 사항이 있어 최신 내용을 다시 불러옵니다.", "error");
      setState(await loadDailyState(state.date));
    } else {
      showToast(`Top 이슈 저장 실패: ${friendlyError(error)}`, "error");
    }
    renderAll();
  }
}

async function toggleDirectCoverage(issue) {
  const directCoverage = !issue.directCoverage;
  const previous = {
    directCoverage: issue.directCoverage,
    editorDirectCoverage: issue.editorDirectCoverage,
    selected: issue.selected,
    articles: state.articles
      .filter(article => issue.articleIds.includes(article.id))
      .map(article => ({ id: article.id, included: article.included, topIssue: article.topIssue })),
  };
  issue.directCoverage = directCoverage;
  issue.editorDirectCoverage = directCoverage;
  if (directCoverage) {
    issue.selected = false;
    previous.articles.forEach(saved => {
      const article = state.articles.find(item => item.id === saved.id);
      if (article) {
        article.included = false;
        article.topIssue = false;
      }
    });
  }
  renderAll();
  try {
    const result = await api.patchBriefingIssue(
      state.date,
      issue.id,
      state.revision,
      { directCoverage },
    );
    state.revision = result.data.revision;
    showToast(
      directCoverage
        ? "공사 직접 보도로 태그하고 일반 브리핑에서 제외했습니다."
        : "공사 직접 보도 태그를 해제했습니다.",
      "success",
    );
  } catch (error) {
    issue.directCoverage = previous.directCoverage;
    issue.editorDirectCoverage = previous.editorDirectCoverage;
    issue.selected = previous.selected;
    previous.articles.forEach(saved => {
      const article = state.articles.find(item => item.id === saved.id);
      if (article) {
        article.included = saved.included;
        article.topIssue = saved.topIssue;
      }
    });
    if (error.code === "BRIEFING_REVISION_CONFLICT") {
      setState(await loadDailyState(state.date));
    }
    showToast(`공사 직접 보도 태그 저장 실패: ${friendlyError(error)}`, "error");
    renderAll();
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
