import { els } from "../state/store.js";

let progressHideTimer = null;

export function setSearchButton(busy, label = "기사 수집 중") {
  els.refreshBtn.disabled = busy;
  els.refreshBtn.innerHTML = busy ? `<span class="spinner"></span><span>${label}</span>` : '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 11a8 8 0 1 0-2.34 5.66M20 4v7h-7"/></svg><span>오늘 기사 검색</span>';
}

export function setSearchProgress(percent, label) {
  window.clearTimeout(progressHideTimer);
  const value = Math.max(0, Math.min(100, Math.round(percent)));
  els.searchProgress.hidden = false;
  els.searchProgress.classList.remove("error");
  els.searchProgress.classList.toggle("active", value < 100);
  els.searchProgress.setAttribute("aria-valuenow", String(value));
  els.searchProgress.setAttribute("aria-valuetext", `${label} ${value}%`);
  els.searchProgressBar.style.width = `${value}%`;
  els.searchProgressPercent.hidden = false;
  els.searchProgressPercent.textContent = `${value}%`;
  if (label) setStatus("busy", label);
}

export function finishSearchProgress(error = false) {
  els.searchProgress.classList.remove("active");
  els.searchProgress.classList.toggle("error", error);
  if (!error) {
    els.searchProgress.setAttribute("aria-valuenow", "100");
    els.searchProgressBar.style.width = "100%";
    els.searchProgressPercent.textContent = "100%";
  }
  progressHideTimer = window.setTimeout(() => {
    els.searchProgress.hidden = true;
    els.searchProgressPercent.hidden = true;
    els.searchProgress.classList.remove("error");
  }, error ? 4000 : 1800);
}

export function setStatus(type, message) {
  els.statusDot.className = `status-dot ${type === "idle" ? "" : type}`;
  els.globalStatus.textContent = message;
}

export function showToast(message, type = "") {
  const toast = document.createElement("div"); toast.className = `toast ${type}`; toast.textContent = message; els.toastRegion.appendChild(toast);
  window.setTimeout(() => toast.remove(), 4200);
}
