import { els, settings, state } from "../state/store.js";
import * as api from "../api/client.js?v=20260723-30";
import { showToast } from "../ui/notifications.js?v=20260716-1";
import { escapeHtml, escapeAttr, safeUrl, shortText, friendlyError } from "../utils/strings.js";
import { refreshArticles } from "./collection.js?v=20260723-21";
import { renderAll } from "../ui/renderers.js";

let currentIssues = [];
let currentPooledCount = 0;
const busyImports = new Set();

function openDiscoveredOverlay() {
  els.discoveredIssuesOverlay.classList.add("open");
  document.body.style.overflow = "hidden";
}

function normalizedTitle(value) {
  return String(value || "").toLowerCase().replace(/[^가-힣a-z0-9]/g, "");
}

function matchingStateArticle(article) {
  const url = safeUrl(article.url);
  const title = normalizedTitle(article.title);
  return state.articles.find(candidate => {
    const candidateUrl = safeUrl(candidate.canonicalUrl || candidate.url);
    return (url && candidateUrl === url)
      || (title && normalizedTitle(candidate.title) === title);
  }) || null;
}

function overlappingIssue(issue, issues = state.issues) {
  const matchingIds = new Set(
    issue.articles.map(matchingStateArticle).filter(Boolean).map(article => article.id),
  );
  return issues
    .map(candidate => ({
      issue: candidate,
      overlap: (candidate.articleIds || []).filter(articleId => matchingIds.has(articleId)).length,
    }))
    .filter(candidate => candidate.overlap)
    .sort((left, right) => Number(right.issue.selected) - Number(left.issue.selected)
      || right.overlap - left.overlap)[0]?.issue || null;
}

function isExistingBriefingIssue(issue) {
  const existing = overlappingIssue(issue);
  if (!existing) return false;
  const selectedIds = new Set(state.articles.filter(article => article.included).map(article => article.id));
  return !!existing.selected || (existing.articleIds || []).some(articleId => selectedIds.has(articleId));
}

function updateMeta() {
  const duplicateCount = currentIssues.filter(isExistingBriefingIssue).length;
  const newCount = currentIssues.length - duplicateCount;
  els.discoveredIssuesMeta.textContent =
    `관련도 미달 ${currentPooledCount}건에서 새 이슈 ${newCount}개를 찾았습니다. 기존 브리핑 중복 ${duplicateCount}개는 별도로 표시합니다.`;
}

function renderIssues(issues) {
  currentIssues = issues;
  updateMeta();
  if (!issues.length) {
    els.discoveredIssuesList.innerHTML =
      `<p class="discovered-empty">여러 매체가 함께 다룬 큰 이슈(같은 사건 5건 이상)가 없습니다. ‘오늘 기사 검색’을 먼저 실행했는지 확인해 주세요.</p>`;
    return;
  }
  els.discoveredIssuesList.innerHTML = issues.map((issue, issueIndex) => {
    const issueBusy = busyImports.has(`issue:${issueIndex}`);
    const existingIssue = overlappingIssue(issue);
    const briefingDuplicate = isExistingBriefingIssue(issue);
    const links = issue.articles.map((article, articleIndex) => {
      const url = safeUrl(article.url);
      const source = escapeHtml(article.source || "출처 미상");
      const title = escapeHtml(shortText(article.title, 90));
      const articleBusy = issueBusy || busyImports.has(`article:${issueIndex}:${articleIndex}`);
      const label = url
        ? `<a href="${escapeAttr(url)}" target="_blank" rel="noopener">${title}</a>`
        : title;
      return `<li><span class="discovered-article-label">${label} <span class="discovered-source">${source}</span></span>
        <span class="discovered-article-actions">
          <button type="button" class="discovered-import-one" data-action="import-discovered-article" data-issue-index="${issueIndex}" data-article-index="${articleIndex}" ${articleBusy || state.status === "final" ? "disabled" : ""}>${articleBusy ? "가져오는 중…" : "가져오기"}</button>
          <button type="button" class="discovered-delete-one" data-action="delete-discovered-article" data-issue-index="${issueIndex}" data-article-index="${articleIndex}" ${articleBusy ? "disabled" : ""} title="이번 가져오기 대상에서 삭제">삭제</button>
        </span>
      </li>`;
    }).join("");
    return `<section class="discovered-issue">
      <header class="discovered-issue-head">
        <span class="discovered-rank">${issueIndex + 1}</span>
        <div>
          <h3>${escapeHtml(shortText(issue.title, 110))}</h3>
          <p class="discovered-count">관련 기사 ${issue.articleCount}건 · 매체 ${issue.sourceCount}곳</p>
          ${briefingDuplicate ? '<span class="discovered-duplicate">기존 브리핑 선정 이슈와 중복</span>' : existingIssue ? '<span class="discovered-overlap">기존 Media Coverage 이슈와 겹침</span>' : ""}
        </div>
        <button type="button" class="discovered-import-all" data-action="import-discovered-issue" data-issue-index="${issueIndex}" ${issueBusy || issue.articleCount < 2 || state.status === "final" ? "disabled" : ""}>${issueBusy ? "가져오는 중…" : existingIssue ? `기존 이슈에 ${issue.articleCount}건 합치기` : `이슈 ${issue.articleCount}건 모두 가져오기`}</button>
      </header>
      <ul class="discovered-links">${links}</ul>
    </section>`;
  }).join("");
}

function deleteArticleFromIssue(issueIndex, articleIndex) {
  const issue = currentIssues[issueIndex];
  if (!issue?.articles?.[articleIndex]) return;
  issue.articles.splice(articleIndex, 1);
  if (!issue.articles.length) {
    currentIssues.splice(issueIndex, 1);
  } else {
    issue.articleCount = issue.articles.length;
    issue.sourceCount = new Set(issue.articles.map(article => article.source).filter(Boolean)).size;
    issue.title = issue.articles[0].title || issue.title;
  }
  renderIssues(currentIssues);
}

function manualArticlePayload(article) {
  return {
    reportDate: state.date,
    title: article.title || "",
    source: article.source || "",
    url: article.url || "",
    pubDate: article.publishedAt || null,
    description: "",
    category: "other",
    forcedRisk: "auto",
    riskKeywords: settings.riskKeywords || [],
    positiveKeywords: settings.positiveKeywords || [],
  };
}

async function refreshMediaCoverage() {
  const [, issuesResult] = await Promise.all([
    refreshArticles(),
    api.listIssues(state.date),
  ]);
  state.issues = issuesResult.data.issues || [];
  state.demo = false;
  renderAll();
}

async function importOne(issueIndex, articleIndex) {
  const article = currentIssues[issueIndex]?.articles?.[articleIndex];
  if (!article || state.status === "final") return;
  const key = `article:${issueIndex}:${articleIndex}`;
  busyImports.add(key);
  renderIssues(currentIssues);
  try {
    const result = await api.createManualArticle(manualArticlePayload(article));
    await refreshMediaCoverage();
    showToast(
      result.data.merged
        ? "이미 있던 기사를 Media Coverage에서 선택했습니다."
        : "기사를 Media Coverage로 가져왔습니다.",
      "success",
    );
  } catch (error) {
    showToast(`기사 가져오기 실패: ${friendlyError(error)}`, "error");
  } finally {
    busyImports.delete(key);
    renderIssues(currentIssues);
  }
}

async function importIssue(issueIndex) {
  const issue = currentIssues[issueIndex];
  if (!issue?.articles?.length || state.status === "final") return;
  const key = `issue:${issueIndex}`;
  busyImports.add(key);
  renderIssues(currentIssues);

  const articleIds = [];
  const createdArticleIds = new Set();
  let mergedCount = 0;
  const failedTitles = [];
  for (const article of issue.articles) {
    try {
      const result = await api.createManualArticle(manualArticlePayload(article));
      articleIds.push(result.data.id);
      if (result.data.merged) mergedCount += 1;
      else createdArticleIds.add(result.data.id);
    } catch {
      failedTitles.push(article.title || "제목 없는 기사");
    }
  }

  const uniqueArticleIds = [...new Set(articleIds)];
  const existingIssues = [...state.issues];
  const targetIssue = existingIssues
    .map(candidate => ({
      issue: candidate,
      overlap: (candidate.articleIds || []).filter(articleId => uniqueArticleIds.includes(articleId)).length,
    }))
    .filter(candidate => candidate.overlap)
    .sort((left, right) => Number(right.issue.selected) - Number(left.issue.selected)
      || right.overlap - left.overlap)[0]?.issue || null;
  let groupError = null;
  if (targetIssue) {
    try {
      const otherGroupedIds = new Set(
        existingIssues
          .filter(candidate => candidate.id !== targetIssue.id)
          .flatMap(candidate => candidate.articleIds || []),
      );
      for (const articleId of uniqueArticleIds) {
        if ((targetIssue.articleIds || []).includes(articleId) || otherGroupedIds.has(articleId)) {
          continue;
        }
        const patched = await api.patchBriefingIssue(
          state.date,
          targetIssue.id,
          state.revision,
          { articleId, membershipAction: "add" },
        );
        state.revision = patched.data.revision;
      }
    } catch (error) {
      groupError = error;
    }
  } else if (uniqueArticleIds.length >= 2) {
    try {
      const grouped = await api.createManualIssueGroup(
        state.date,
        uniqueArticleIds,
        state.revision,
      );
      state.revision = grouped.data.revision;
    } catch (error) {
      groupError = error;
    }
  }

  try {
    await refreshMediaCoverage();
    if (failedTitles.length) {
      showToast(
        `${uniqueArticleIds.length}건은 가져왔지만 ${failedTitles.length}건은 실패했습니다. 그룹과 기사 목록을 확인해 주세요.`,
        "error",
      );
    } else if (groupError) {
      showToast(
        `${uniqueArticleIds.length}건은 가져왔지만 관련기사 묶기 실패: ${friendlyError(groupError)}`,
        "error",
      );
    } else if (uniqueArticleIds.length < 2) {
      showToast("기사는 가져왔지만 서로 다른 기사 2건 미만이라 그룹으로 묶지 못했습니다.", "error");
    } else if (targetIssue) {
      showToast(
        `기존 이슈를 유지하고 신규 기사 ${createdArticleIds.size}건을 추가했습니다. 기존 기사 ${mergedCount}건은 중복 처리했습니다.`,
        "success",
      );
    } else {
      showToast(
        `${uniqueArticleIds.length}건을 Media Coverage로 가져와 하나의 관련기사 그룹으로 묶었습니다.`,
        "success",
      );
    }
  } catch (error) {
    showToast(`가져온 기사 목록 갱신 실패: ${friendlyError(error)}`, "error");
  } finally {
    busyImports.delete(key);
    renderIssues(currentIssues);
  }
}

export function handleDiscoveredIssuesClick(event) {
  const button = event.target.closest("button[data-action]");
  if (!button || button.disabled) return;
  const issueIndex = Number(button.dataset.issueIndex);
  if (button.dataset.action === "import-discovered-article") {
    void importOne(issueIndex, Number(button.dataset.articleIndex));
  } else if (button.dataset.action === "import-discovered-issue") {
    void importIssue(issueIndex);
  } else if (button.dataset.action === "delete-discovered-article") {
    deleteArticleFromIssue(issueIndex, Number(button.dataset.articleIndex));
  }
}

export async function openDiscoveredIssues() {
  openDiscoveredOverlay();
  els.discoveredIssuesMeta.textContent = "제외됐던 기사에서 큰 이슈를 찾는 중…";
  els.discoveredIssuesList.innerHTML =
    `<p class="discovered-empty">관련도 미달로 제외된 기사에서 여러 매체가 함께 다룬 사건을 찾는 중입니다…</p>`;
  try {
    const result = await api.getDiscoveredIssues(state.date);
    const { issues, pooledCount } = result.data;
    currentPooledCount = pooledCount;
    renderIssues(issues.map(issue => ({
      ...issue,
      articles: [...issue.articles],
    })));
  } catch (error) {
    els.discoveredIssuesMeta.textContent = "이슈를 찾지 못했습니다.";
    els.discoveredIssuesList.innerHTML =
      `<p class="discovered-empty">${escapeHtml(friendlyError(error))}</p>`;
    showToast(friendlyError(error), "error");
  }
}
