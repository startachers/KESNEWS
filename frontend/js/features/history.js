import { els } from "../state/store.js";
import * as api from "../api/client.js";
import { changeReportDate } from "./data-io.js";
import { closeOverlay, openOverlay } from "../ui/dialogs.js";
import { formatDateTime } from "../utils/dates.js";
import { escapeAttr, escapeHtml, friendlyError } from "../utils/strings.js";
import { showToast } from "../ui/notifications.js?v=20260716-1";

function statusLabel(briefing) {
  if (briefing.status === "final") return "최종 확정";
  if (briefing.latestFinalVersion) return "수정 중";
  return "작성 중";
}

function renderHistory(items) {
  if (!items.length) {
    els.historyList.innerHTML = '<div class="history-empty">저장된 언론브리핑이 없습니다.</div>';
    return;
  }
  els.historyList.innerHTML = items.map(briefing => {
    const date = escapeAttr(briefing.reportDate);
    const latestVersion = Number(briefing.latestFinalVersion || 0);
    const reports = latestVersion
      ? Array.from({ length: latestVersion }, (_, index) => index + 1)
        .map(version => `<a class="btn btn-subtle" href="/report/${date}?version=${version}" target="_blank" rel="noopener">CEO 보고서 v${version}</a>`)
        .join("")
      : '<span class="history-no-report">확정된 CEO 보고서 없음</span>';
    return `<article class="history-item">
      <div class="history-summary">
        <strong>${escapeHtml(briefing.reportDate)}</strong>
        <span class="history-status">${statusLabel(briefing)}</span>
        <small>최근 수정 ${escapeHtml(formatDateTime(briefing.updatedAt))}${briefing.preparedBy ? ` · ${escapeHtml(briefing.preparedBy)}` : ""}</small>
      </div>
      <div class="history-actions">
        <button class="btn btn-primary" type="button" data-history-date="${date}">언론브리핑 열기</button>
        ${reports}
      </div>
    </article>`;
  }).join("");
}

export async function openBriefingHistory() {
  els.historyList.innerHTML = '<div class="history-empty">저장된 브리핑을 불러오는 중입니다.</div>';
  openOverlay("historyOverlay");
  try {
    const result = await api.listBriefings();
    renderHistory(result.data.briefings);
  } catch (error) {
    els.historyList.innerHTML = '<div class="history-empty error">목록을 불러오지 못했습니다.</div>';
    showToast(`지난 브리핑 조회 실패: ${friendlyError(error)}`, "error");
  }
}

export async function handleHistoryClick(event) {
  const button = event.target.closest("[data-history-date]");
  if (!button) return;
  els.reportDate.value = button.dataset.historyDate;
  closeOverlay("historyOverlay");
  await changeReportDate();
}
