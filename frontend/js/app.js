import { $, els, settings, state, filters, SETTINGS_KEY, LAST_AUTO_KEY, saveDailyState, loadDailyState, setState, consumeSettingsMigrationNotice } from "./state/store.js";
import { localDateKey } from "./utils/dates.js";
import { autoResize } from "./utils/dom.js";
import { setStatus, showToast } from "./ui/notifications.js?v=20260716-1";
import { renderAll } from "./ui/renderers.js?v=20260720-3";
import { openSettings, saveSettingsFromForm, resetSettingsForm, restartServerFromSettings, openArticleModal, addManualArticle, openOverlay, closeOverlay, populateStaticControls } from "./ui/dialogs.js?v=20260720-1";
import { runSearch } from "./features/collection.js?v=20260716-19";
import { setRuleSummary, handleAiAnalysisAction, checkAiServer, renderSummary, renderAiSummaryStatus } from "./features/ai-analysis.js";
import { persistAndRender, handleArticleChange, handleArticleInput, handleArticleClick, handleTopIssuesClick, renderArticles, createManualGroup, openManualGroupPicker, closeManualGroupPicker, handleManualGroupPickerChange, handleManualGroupSearch } from "./features/articles.js?v=20260720-6";
import { importFile, exportJson, exportCsv, copySummary, changeReportDate, finalizeCurrentBriefing, reopenCurrentBriefing, openPreview, openFinalReport, resetTodayWork } from "./features/data-io.js";
import { handleHistoryClick, openBriefingHistory } from "./features/history.js";
import { openClusterProposal, applyClusterProposal, handleClusterThresholdInput, recalculateClusterProposal } from "./features/clustering.js";
import { loadKescoPressStatus, openKescoPressViewer, refreshKescoPressFromModal, refreshKescoPressReleases } from "./features/press-releases.js";
import { closeReportDraftEditor, downloadAnalysisMarkdown, loadGemmaDraft, openReportDraftEditor, previewFromDraftEditor, saveReportDraft, validateExternalAnalysis } from "./features/report-draft.js?v=20260720-1";
import { applyAutoSelectionProposal, closeAutoSelectionProposal, openAutoSelectionProposal } from "./features/auto-selection.js?v=20260720-1";
import { excludeWeatherFromReport, refreshWeather, toggleWeatherReview } from "./features/weather.js";

document.addEventListener("DOMContentLoaded", () => { init(); });

async function init() {
  ["report", "statusDot", "globalStatus", "searchProgress", "searchProgressBar", "searchProgressPercent", "refreshBtn", "reportDate", "preparedBy", "mastheadDate", "mastheadDay", "kpiTotal", "kpiRisk", "kpiPositive", "kpiSources", "kpiTotalNote", "kpiSourceNote", "weatherPanel", "weatherSourceMeta", "weatherRegionSelect", "weatherRefreshBtn", "weatherReviewBtn", "weatherOverviewCard", "weatherLevelLabel", "weatherLevel", "weatherAlertCount", "weatherDays", "weatherStatus", "weatherRiskList", "summaryEditor", "printSummary", "actionNote", "printActionNote", "aiConnectionState", "aiModelSelect", "aiCoverageState", "aiSummaryStatus", "generateAiSummaryBtn", "ruleSummaryBtn", "star5Bar", "star4Bar", "star3Bar", "star2Bar", "star1Bar", "star5Count", "star4Count", "star3Count", "star2Count", "star1Count", "topIssues", "articleList", "articleSearch", "categoryFilter", "riskFilter", "selectionFilter", "selectedOnlyBtn", "selectedOnlyCount", "autoSelectBtn", "autoSelectionOverlay", "autoSelectionMeta", "autoSelectionList", "autoSelectionLimitations", "autoSelectionApplyBtn", "autoSelectionCloseBtn", "manualGroupModeBtn", "manualGroupOverlay", "manualGroupSearch", "manualGroupList", "manualGroupCloseBtn", "manualGroupBtn", "manualGroupUnitCount", "manualGroupCount", "manualGroupCancelBtn", "sortOrder", "visibleCount", "footerTimestamp", "sourceStateBox", "sourceStateTitle", "sourceStateDetail", "collectionErrors", "collectionErrorsSummary", "collectionErrorsList", "keywordCloud", "settingsOverlay", "articleOverlay", "historyOverlay", "historyList", "querySettings", "clusterOverlay", "clusterThreshold", "clusterThresholdValue", "clusterThresholdHint", "clusterRecalculateBtn", "clusterProposalMeta", "clusterDiffSummary", "clusterProposalList", "clusterApplyBtn", "reclusterBtn", "toastRegion", "fileInput", "previewBtn", "finalizeBtn", "finalReportBtn", "reopenBtn", "briefingState", "reportDraftOverlay", "externalAnalysisPaste", "reportDraftContent", "reportDraftSource", "reportDraftStatus"].forEach(id => els[id] = $(id));
  ["weatherDetailPanel", "weatherDetailRainfall", "weatherDetailRainfallPlace", "weatherDetailTemperature", "weatherDetailTemperaturePlace", "weatherDetailAlertSummary", "weatherDetailPriority", "weatherResponseTabCount", "weatherSourceGrid", "weatherOfficialAlerts", "weatherComparisonDaySelect", "weatherRegionComparison", "weatherCompactSource", "weatherOpenBtn", "weatherCompactLevel", "weatherCompactAlerts", "weatherCompactFocus", "weatherCompactForecast", "weatherCompactTemperature", "weatherCompactRainfall", "weatherCompactProbability", "weatherCompactNotice", "weatherOverlay"].forEach(id => els[id] = $(id));
  els.weatherExcludeBtn = $("weatherExcludeBtn");

  setState(await loadDailyState(localDateKey()));
  bindEvents();
  populateStaticControls();
  renderAll();
  if (consumeSettingsMigrationNotice()) {
    showToast("기본 설정을 갱신했습니다. Gemma 경영메시지는 31B를 기본으로 사용합니다.");
  }
  autoResize(els.summaryEditor);
  window.setTimeout(checkAiServer, 120);
  window.setTimeout(loadKescoPressStatus, 160);

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
  $("viewKescoPressBtn").addEventListener("click", openKescoPressViewer);
  $("refreshKescoPressBtn").addEventListener("click", refreshKescoPressReleases);
  $("refreshKescoPressModalBtn").addEventListener("click", refreshKescoPressFromModal);
  els.historyList.addEventListener("click", handleHistoryClick);
  $("editKeywordsBtn").addEventListener("click", openSettings);
  $("saveSettingsBtn").addEventListener("click", saveSettingsFromForm);
  $("resetSettingsBtn").addEventListener("click", resetSettingsForm);
  $("resetTodayBtn").addEventListener("click", resetTodayWork);
  $("restartServerBtn").dataset.restartHandler = "module";
  $("restartServerBtn").addEventListener("click", restartServerFromSettings);
  $("addArticleBtn").addEventListener("click", openArticleModal);
  $("articleForm").addEventListener("submit", addManualArticle);
  els.refreshBtn.addEventListener("click", () => runSearch(false));
  const activateWeatherTab = tab => {
    document.querySelectorAll("[data-weather-tab]").forEach(button => {
      const active = button.dataset.weatherTab === tab;
      button.classList.toggle("active", active);
      button.setAttribute("aria-selected", String(active));
    });
    document.querySelectorAll("[data-weather-tab-panel]").forEach(panel => {
      const active = panel.dataset.weatherTabPanel === tab;
      panel.classList.toggle("active", active);
      panel.hidden = !active;
    });
    els.weatherOverlay.querySelector(".modal").scrollTop = 0;
  };
  els.weatherOpenBtn.addEventListener("click", () => { activateWeatherTab("overview"); openOverlay("weatherOverlay"); });
  document.querySelectorAll("[data-weather-tab]").forEach(button => button.addEventListener("click", () => activateWeatherTab(button.dataset.weatherTab)));
  els.weatherRefreshBtn.addEventListener("click", refreshWeather);
  els.weatherReviewBtn.addEventListener("click", toggleWeatherReview);
  els.weatherExcludeBtn.addEventListener("click", excludeWeatherFromReport);
  els.weatherRegionSelect.addEventListener("change", () => {
    state.weatherRegionId = els.weatherRegionSelect.value;
    renderAll();
  });
  els.weatherComparisonDaySelect.addEventListener("change", () => {
    state.weatherComparisonDate = els.weatherComparisonDaySelect.value;
    renderAll();
  });
  els.reclusterBtn.addEventListener("click", openClusterProposal);
  els.autoSelectBtn.addEventListener("click", openAutoSelectionProposal);
  els.autoSelectionApplyBtn.addEventListener("click", applyAutoSelectionProposal);
  els.autoSelectionCloseBtn.addEventListener("click", closeAutoSelectionProposal);
  els.clusterThreshold.addEventListener("input", handleClusterThresholdInput);
  els.clusterRecalculateBtn.addEventListener("click", recalculateClusterProposal);
  els.clusterApplyBtn.addEventListener("click", applyClusterProposal);
  els.ruleSummaryBtn.addEventListener("click", () => { setRuleSummary(true); persistAndRender(); showToast("선정 기사 기준 기본 요약을 만들었습니다.", "success"); });
  els.generateAiSummaryBtn.addEventListener("click", handleAiAnalysisAction);
  $("markdownExportBtn").addEventListener("click", downloadAnalysisMarkdown);
  $("reportDraftBtn").addEventListener("click", openReportDraftEditor);
  $("validateExternalAnalysisBtn").addEventListener("click", validateExternalAnalysis);
  $("loadGemmaDraftBtn").addEventListener("click", loadGemmaDraft);
  $("saveReportDraftBtn").addEventListener("click", saveReportDraft);
  $("previewReportDraftBtn").addEventListener("click", previewFromDraftEditor);
  $("reportDraftCloseBtn").addEventListener("click", closeReportDraftEditor);
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
  els.topIssues.addEventListener("click", handleTopIssuesClick);
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
