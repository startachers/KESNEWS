import { state, els, RISK_LABELS } from "../state/store.js";
import { escapeHtml } from "../utils/strings.js";
import { formatRelative } from "../utils/dates.js";
import { prioritySort } from "./collection.js";

export function renderTopIssues() {
  const top = state.articles.filter(a => a.included).sort(prioritySort).slice(0, 3);
  els.topIssues.innerHTML = [0,1,2].map((_, i) => {
    const a = top[i];
    if (!a) return `<div class="issue-card empty"><div>ISSUE ${String(i+1).padStart(2,"0")}</div><strong>선별된 기사가 없습니다</strong></div>`;
    const reason = a.starred ? "담당자가 중요 기사로 표시했습니다." : a.risk === "critical" ? "강한 위기 키워드가 감지됐습니다." : a.risk === "watch" ? "주의 키워드가 감지됐습니다." : "최신성과 분류 비중을 반영했습니다.";
    return `<article class="issue-card">
      <div class="issue-head"><span class="rank">ISSUE ${String(i+1).padStart(2,"0")}</span><span class="badge badge-${a.risk}">${RISK_LABELS[a.risk]}</span></div>
      <h3>${escapeHtml(a.title)}</h3>
      <div class="issue-meta">${escapeHtml(a.source || "출처 미상")} · ${formatRelative(a.pubDate)}</div>
      <div class="issue-reason">${escapeHtml(reason)}</div>
    </article>`;
  }).join("");
}
