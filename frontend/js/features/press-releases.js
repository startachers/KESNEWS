import { $ } from "../state/store.js";
import * as api from "../api/client.js";
import { openOverlay } from "../ui/dialogs.js";
import { showToast } from "../ui/notifications.js?v=20260716-1";
import { escapeAttr, escapeHtml, friendlyError } from "../utils/strings.js";

let refreshing = false;

function setButtonState(button, busy, label = "공사 보도자료 갱신") {
  button.disabled = busy;
  button.textContent = label;
}

export async function loadKescoPressStatus() {
  const button = $("refreshKescoPressBtn");
  try {
    const result = await api.getKescoPressStatus();
    const data = result.data;
    button.title = data.releaseCount
      ? `저장 원문 ${data.releaseCount}건 · 마지막 갱신 ${data.lastFetchedAt || "시각 없음"}`
      : "저장된 공사 보도자료가 없습니다. 눌러서 최신 원문을 가져오세요.";
  } catch {
    button.title = "공사 보도자료 저장 상태를 확인하지 못했습니다.";
  }
}

export async function refreshKescoPressReleases() {
  if (refreshing) return;
  const button = $("refreshKescoPressBtn");
  refreshing = true;
  setButtonState(button, true, "보도자료 가져오는 중…");
  try {
    const result = await api.refreshKescoPress(30);
    const data = result.data;
    button.title = `저장 원문 ${data.releaseCount}건 · 마지막 갱신 ${data.lastFetchedAt || "시각 없음"}`;
    showToast(
      `공사 보도자료 ${data.refreshedCount}건을 확인해 원문 ${data.releaseCount}건을 저장했습니다. 다음 기사 검색부터 자동 대조합니다.`,
      data.warning ? "" : "success",
    );
  } catch (error) {
    showToast(`공사 보도자료 갱신 실패: ${friendlyError(error)}`, "error");
  } finally {
    refreshing = false;
    setButtonState(button, false);
  }
}

function displayDate(value) {
  if (!value) return "게시일 없음";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString("ko-KR", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
}

async function loadPressReleaseList() {
  const list = $("kescoPressList");
  const meta = $("kescoPressMeta");
  list.innerHTML = '<div class="history-empty">저장된 보도자료를 불러오는 중입니다.</div>';
  try {
    const result = await api.listKescoPress(30);
    const releases = result.data.pressReleases || [];
    meta.textContent = `최근 저장 원문 ${releases.length}건 · 제목을 누르면 본문을 확인할 수 있습니다.`;
    list.innerHTML = releases.length
      ? releases.map(release => `<details class="press-release-item">
          <summary><strong>${escapeHtml(release.title)}</strong><span>${escapeHtml(displayDate(release.publishedAt))} · 게시물 ${escapeHtml(release.bbsSeq)}</span></summary>
          <div class="press-release-content"><p>${escapeHtml(release.bodyText || "저장된 본문이 없습니다.")}</p><a href="${escapeAttr(release.url)}" target="_blank" rel="noopener noreferrer">공사 홈페이지 원문 보기 ↗</a></div>
        </details>`).join("")
      : '<div class="history-empty">저장된 보도자료가 없습니다. ‘최신 보도자료 가져오기’를 눌러 주세요.</div>';
  } catch (error) {
    meta.textContent = "저장 원문을 불러오지 못했습니다.";
    list.innerHTML = `<div class="history-empty error">${escapeHtml(friendlyError(error))}</div>`;
  }
}

export async function openKescoPressViewer() {
  openOverlay("kescoPressOverlay");
  await loadPressReleaseList();
}

export async function refreshKescoPressFromModal() {
  await refreshKescoPressReleases();
  await loadPressReleaseList();
}
