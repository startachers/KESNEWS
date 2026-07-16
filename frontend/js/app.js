import { $, els, settings, state, filters, SETTINGS_KEY, LAST_AUTO_KEY, saveDailyState, loadDailyState, setState, consumeSettingsMigrationNotice } from "./state/store.js";
import { localDateKey } from "./utils/dates.js";
import { autoResize } from "./utils/dom.js";
import { setStatus, showToast } from "./ui/notifications.js?v=20260716-1";
import { renderAll } from "./ui/renderers.js";
import { openSettings, saveSettingsFromForm, resetSettingsForm, restartServerFromSettings, openArticleModal, addManualArticle, closeOverlay, populateStaticControls } from "./ui/dialogs.js?v=20260716-19";
import { runSearch } from "./features/collection.js?v=20260716-19";
import { setRuleSummary, handleAiAnalysisAction, checkAiServer, renderSummary, renderAiSummaryStatus } from "./features/ai-analysis.js";
import { persistAndRender, handleArticleChange, handleArticleInput, handleArticleClick, renderArticles, createManualGroup, openManualGroupPicker, closeManualGroupPicker, handleManualGroupPickerChange, handleManualGroupSearch } from "./features/articles.js?v=20260716-15";
import { importFile, exportJson, exportCsv, copySummary, changeReportDate, finalizeCurrentBriefing, reopenCurrentBriefing, openPreview, openFinalReport } from "./features/data-io.js";
import { handleHistoryClick, openBriefingHistory } from "./features/history.js";
import { openClusterProposal, applyClusterProposal, handleClusterThresholdInput, recalculateClusterProposal } from "./features/clustering.js";

document.addEventListener("DOMContentLoaded", () => { init(); });

async function init() {
  ["report", "statusDot", "globalStatus", "searchProgress", "searchProgressBar", "searchProgressPercent", "refreshBtn", "reportDate", "preparedBy", "mastheadDate", "mastheadDay", "kpiTotal", "kpiRisk", "kpiPositive", "kpiSources", "kpiTotalNote", "kpiSourceNote", "summaryEditor", "printSummary", "actionNote", "printActionNote", "aiConnectionState", "aiModelSelect", "aiCoverageState", "aiSummaryStatus", "generateAiSummaryBtn", "ruleSummaryBtn", "criticalBar", "watchBar", "routineBar", "criticalCount", "watchCount", "routineCount", "topIssues", "articleList", "articleSearch", "categoryFilter", "riskFilter", "selectionFilter", "selectedOnlyBtn", "selectedOnlyCount", "manualGroupModeBtn", "manualGroupOverlay", "manualGroupSearch", "manualGroupList", "manualGroupCloseBtn", "manualGroupBtn", "manualGroupUnitCount", "manualGroupCount", "manualGroupCancelBtn", "sortOrder", "visibleCount", "footerTimestamp", "sourceStateBox", "sourceStateTitle", "sourceStateDetail", "collectionErrors", "collectionErrorsSummary", "collectionErrorsList", "keywordCloud", "settingsOverlay", "articleOverlay", "historyOverlay", "historyList", "querySettings", "clusterOverlay", "clusterThreshold", "clusterThresholdValue", "clusterThresholdHint", "clusterRecalculateBtn", "clusterProposalMeta", "clusterDiffSummary", "clusterProposalList", "clusterApplyBtn", "reclusterBtn", "toastRegion", "fileInput", "previewBtn", "finalizeBtn", "finalReportBtn", "reopenBtn", "briefingState"].forEach(id => els[id] = $(id));

  setState(await loadDailyState(localDateKey()));
  bindEvents();
  populateStaticControls();
  renderAll();
  if (consumeSettingsMigrationNotice()) {
    showToast("기사 검색식이 21개 검색군으로 확장되었습니다. 검색 설정에서 확인해 주세요.");
  }
  autoResize(els.summaryEditor);
  window.setTimeout(checkAiServer, 120);

  const today = localDateKey();
  const skipAutoRun = new URLSearchParams(location.search).has("noauto");
  const shouldAutoRun = state.status !== "final" && !skipAutoRun && settings.autoRun && !state.articles.length && localStorage.getItem(LAST_AUTO_KEY) !== today;
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
  $("historyBtn").addEventListener("click", openBriefingHistory);
  els.historyList.addEventListener("click", handleHistoryClick);
  $("editKeywordsBtn").addEventListener("click", openSettings);
  $("saveSettingsBtn").addEventListener("click", saveSettingsFromForm);
  $("resetSettingsBtn").addEventListener("click", resetSettingsForm);
  $("restartServerBtn").dataset.restartHandler = "module";
  $("restartServerBtn").addEventListener("click", restartServerFromSettings);
  $("addArticleBtn").addEventListener("click", openArticleModal);
  $("articleForm").addEventListener("submit", addManualArticle);
  els.refreshBtn.addEventListener("click", () => runSearch(false));
  els.reclusterBtn.addEventListener("click", openClusterProposal);
  els.clusterThreshold.addEventListener("input", handleClusterThresholdInput);
  els.clusterRecalculateBtn.addEventListener("click", recalculateClusterProposal);
  els.clusterApplyBtn.addEventListener("click", applyClusterProposal);
  els.ruleSummaryBtn.addEventListener("click", () => { setRuleSummary(true); persistAndRender(); showToast("선정 기사 기준 기본 요약을 만들었습니다.", "success"); });
  els.generateAiSummaryBtn.addEventListener("click", handleAiAnalysisAction);
  els.aiModelSelect.addEventListener("change", () => {
    settings.aiModel = els.aiModelSelect.value;
    state.summaryError = "";
    if (["ai", "ai-edited"].includes(state.summaryMode)) state.aiStale = true;
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
  els.manualGroupModeBtn.addEventListener("click", openManualGroupPicker);
  els.manualGroupBtn.addEventListener("click", createManualGroup);
  els.manualGroupCancelBtn.addEventListener("click", closeManualGroupPicker);
  els.manualGroupCloseBtn.addEventListener("click", closeManualGroupPicker);
  els.manualGroupList.addEventListener("change", handleManualGroupPickerChange);
  els.manualGroupSearch.addEventListener("input", handleManualGroupSearch);
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
  els.previewBtn.addEventListener("click", openPreview);
  els.finalizeBtn.addEventListener("click", finalizeCurrentBriefing);
  els.finalReportBtn.addEventListener("click", openFinalReport);
  els.reopenBtn.addEventListener("click", reopenCurrentBriefing);
  document.querySelectorAll("[data-close]").forEach(btn => btn.addEventListener("click", () => closeOverlay(btn.dataset.close)));
  document.querySelectorAll(".overlay").forEach(overlay => overlay.addEventListener("click", e => { if (e.target === overlay) closeOverlay(overlay.id); }));
  document.addEventListener("keydown", e => { if (e.key === "Escape") document.querySelectorAll(".overlay.open").forEach(o => closeOverlay(o.id)); });
  window.addEventListener("beforeprint", () => { els.printSummary.textContent = state.summary || "수집 기사 없음"; els.printActionNote.textContent = state.actionNote || "별도 지시사항 없음"; });
}
