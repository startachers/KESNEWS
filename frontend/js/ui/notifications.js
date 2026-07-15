import { els } from "../state/store.js";

export function setSearchButton(busy) {
  els.refreshBtn.disabled = busy;
  els.refreshBtn.innerHTML = busy ? '<span class="spinner"></span><span>기사 수집 중</span>' : '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 11a8 8 0 1 0-2.34 5.66M20 4v7h-7"/></svg><span>오늘 기사 검색</span>';
}

export function setStatus(type, message) {
  els.statusDot.className = `status-dot ${type === "idle" ? "" : type}`;
  els.globalStatus.textContent = message;
}

export function showToast(message, type = "") {
  const toast = document.createElement("div"); toast.className = `toast ${type}`; toast.textContent = message; els.toastRegion.appendChild(toast);
  window.setTimeout(() => toast.remove(), 4200);
}
