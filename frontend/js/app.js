import { $, els, settings, state, filters, SETTINGS_KEY, LAST_AUTO_KEY, saveDailyState, loadDailyState, setState } from "./state/store.js";
import { localDateKey } from "./utils/dates.js";
import { autoResize } from "./utils/dom.js";
import { setStatus, showToast } from "./ui/notifications.js";
import { renderAll } from "./ui/renderers.js";
import { openSettings, saveSettingsFromForm, resetSettingsForm, openArticleModal, addManualArticle, closeOverlay, populateStaticControls } from "./ui/dialogs.js";
import { runSearch } from "./features/collection.js";
import { setRuleSummary, generateAiManagementSummary, checkAiServer, renderSummary, renderAiSummaryStatus } from "./features/ai-analysis.js";
import { persistAndRender, handleArticleChange, handleArticleInput, handleArticleClick, renderArticles } from "./features/articles.js";
import { importFile, exportJson, exportCsv, copySummary, changeReportDate } from "./features/data-io.js";

document.addEventListener("DOMContentLoaded", () => { init(); });

async function init() {
  ["report", "statusDot", "globalStatus", "refreshBtn", "reportDate", "preparedBy", "mastheadDate", "mastheadDay", "kpiTotal", "kpiRisk", "kpiPositive", "kpiSources", "kpiTotalNote", "kpiSourceNote", "summaryEditor", "printSummary", "actionNote", "printActionNote", "aiConnectionState", "aiModelSelect", "aiCoverageState", "aiSummaryStatus", "generateAiSummaryBtn", "ruleSummaryBtn", "criticalBar", "watchBar", "routineBar", "criticalCount", "watchCount", "routineCount", "topIssues", "articleList", "articleSearch", "categoryFilter", "riskFilter", "selectionFilter", "selectedOnlyBtn", "selectedOnlyCount", "sortOrder", "visibleCount", "footerTimestamp", "sourceStateBox", "sourceStateTitle", "sourceStateDetail", "collectionErrors", "collectionErrorsSummary", "collectionErrorsList", "keywordCloud", "settingsOverlay", "articleOverlay", "querySettings", "toastRegion", "fileInput"].forEach(id => els[id] = $(id));

  setState(await loadDailyState(localDateKey()));
  bindEvents();
  populateStaticControls();
  renderAll();
  autoResize(els.summaryEditor);
  window.setTimeout(checkAiServer, 120);

  const today = localDateKey();
  const skipAutoRun = new URLSearchParams(location.search).has("noauto");
  const shouldAutoRun = !skipAutoRun && settings.autoRun && !state.articles.length && localStorage.getItem(LAST_AUTO_KEY) !== today;
  if (shouldAutoRun) {
    window.setTimeout(() => runSearch(true), 450);
  } else if (state.articles.length) {
    setStatus("live", `${state.articles.length}건 저장본을 불러왔습니다`);
  } else {
    setStatus("idle", "검색 버튼을 눌러 오늘 브리핑을 시작하세요");
  }
}

function bindEvents() {
  $("settingsBtn").addEventListener("click", openSettings);
  $("editKeywordsBtn").addEventListener("click", openSettings);
  $("saveSettingsBtn").addEventListener("click", saveSettingsFromForm);
  $("resetSettingsBtn").addEventListener("click", resetSettingsForm);
  $("addArticleBtn").addEventListener("click", openArticleModal);
  $("articleForm").addEventListener("submit", addManualArticle);
  els.refreshBtn.addEventListener("click", () => runSearch(false));
  els.ruleSummaryBtn.addEventListener("click", () => { setRuleSummary(true); persistAndRender(); showToast("선정 기사 기준 기본 요약을 만들었습니다.", "success"); });
  els.generateAiSummaryBtn.addEventListener("click", generateAiManagementSummary);
  els.aiModelSelect.addEventListener("change", () => {
    settings.aiModel = els.aiModelSelect.value;
    state.summaryError = "";
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
    saveDailyState();
    renderSummary();
  });
  els.summaryEditor.addEventListener("input", () => {
    state.summary = els.summaryEditor.value;
    state.summaryEdited = true;
    state.summaryMode = state.summaryMode === "ai" || state.summaryMode === "ai-edited" ? "ai-edited" : "manual";
    state.summaryError = "";
    els.printSummary.textContent = state.summary;
    autoResize(els.summaryEditor);
    saveDailyState();
    renderAiSummaryStatus();
  });
  els.actionNote.addEventListener("input", () => { state.actionNote = els.actionNote.value; els.printActionNote.textContent = state.actionNote || "별도 지시사항 없음"; saveDailyState(); });
  els.preparedBy.addEventListener("input", () => {
    state.preparedBy = els.preparedBy.value;
    saveDailyState();
    renderAiSummaryStatus();
  });
  els.reportDate.addEventListener("change", changeReportDate);
  els.articleSearch.addEventListener("input", () => { filters.text = els.articleSearch.value.trim().toLowerCase(); renderArticles(); });
  els.categoryFilter.addEventListener("change", () => { filters.category = els.categoryFilter.value; renderArticles(); });
  els.riskFilter.addEventListener("change", () => { filters.risk = els.riskFilter.value; renderArticles(); });
  els.selectionFilter.addEventListener("change", () => { filters.selection = els.selectionFilter.value; renderArticles(); });
  els.selectedOnlyBtn.addEventListener("click", () => {
    filters.selection = filters.selection === "selected" ? "all" : "selected";
    els.selectionFilter.value = filters.selection;
    renderArticles();
  });
  els.sortOrder.addEventListener("change", () => { filters.sort = els.sortOrder.value; renderArticles(); });
  els.articleList.addEventListener("change", handleArticleChange);
  els.articleList.addEventListener("click", handleArticleClick);
  els.articleList.addEventListener("input", handleArticleInput);
  $("importBtn").addEventListener("click", () => els.fileInput.click());
  els.fileInput.addEventListener("change", importFile);
  $("exportBtn").addEventListener("click", exportJson);
  $("csvBtn").addEventListener("click", exportCsv);
  $("copySummaryBtn").addEventListener("click", copySummary);
  $("printBtn").addEventListener("click", () => window.print());
  document.querySelectorAll("[data-close]").forEach(btn => btn.addEventListener("click", () => closeOverlay(btn.dataset.close)));
  document.querySelectorAll(".overlay").forEach(overlay => overlay.addEventListener("click", e => { if (e.target === overlay) closeOverlay(overlay.id); }));
  document.addEventListener("keydown", e => { if (e.key === "Escape") document.querySelectorAll(".overlay.open").forEach(o => closeOverlay(o.id)); });
  window.addEventListener("beforeprint", () => { els.printSummary.textContent = state.summary || "수집 기사 없음"; els.printActionNote.textContent = state.actionNote || "별도 지시사항 없음"; });
}
