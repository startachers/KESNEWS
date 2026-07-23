import { els, state } from "../state/store.js";
import * as api from "../api/client.js?v=20260723-30";
import { showToast } from "../ui/notifications.js?v=20260716-1";
import { escapeHtml, escapeAttr, safeUrl, shortText, friendlyError } from "../utils/strings.js";

function openDiscoveredOverlay() {
  els.discoveredIssuesOverlay.classList.add("open");
  document.body.style.overflow = "hidden";
}

function renderIssues(issues) {
  if (!issues.length) {
    els.discoveredIssuesList.innerHTML =
      `<p class="discovered-empty">여러 매체가 함께 다룬 큰 이슈(같은 사건 5건 이상)가 없습니다. ‘오늘 기사 검색’을 먼저 실행했는지 확인해 주세요.</p>`;
    return;
  }
  els.discoveredIssuesList.innerHTML = issues.map((issue, index) => {
    const links = issue.articles.map(article => {
      const url = safeUrl(article.url);
      const source = escapeHtml(article.source || "출처 미상");
      const title = escapeHtml(shortText(article.title, 90));
      const label = url
        ? `<a href="${escapeAttr(url)}" target="_blank" rel="noopener">${title}</a>`
        : title;
      return `<li>${label} <span class="discovered-source">${source}</span></li>`;
    }).join("");
    return `<section class="discovered-issue">
      <header class="discovered-issue-head">
        <span class="discovered-rank">${index + 1}</span>
        <div>
          <h3>${escapeHtml(shortText(issue.title, 110))}</h3>
          <p class="discovered-count">관련 기사 ${issue.articleCount}건 · 매체 ${issue.sourceCount}곳</p>
        </div>
      </header>
      <ul class="discovered-links">${links}</ul>
    </section>`;
  }).join("");
}

export async function openDiscoveredIssues() {
  openDiscoveredOverlay();
  els.discoveredIssuesMeta.textContent = "제외됐던 기사에서 큰 이슈를 찾는 중…";
  els.discoveredIssuesList.innerHTML =
    `<p class="discovered-empty">관련도 미달로 제외된 기사에서 여러 매체가 함께 다룬 사건을 찾는 중입니다…</p>`;
  try {
    const result = await api.getDiscoveredIssues(state.date);
    const { issues, pooledCount } = result.data;
    els.discoveredIssuesMeta.textContent =
      `관련도 미달로 제외된 ${pooledCount}건 중 여러 매체가 함께 다룬 이슈 ${issues.length}개입니다.`;
    renderIssues(issues);
  } catch (error) {
    els.discoveredIssuesMeta.textContent = "이슈를 찾지 못했습니다.";
    els.discoveredIssuesList.innerHTML =
      `<p class="discovered-empty">${escapeHtml(friendlyError(error))}</p>`;
    showToast(friendlyError(error), "error");
  }
}
