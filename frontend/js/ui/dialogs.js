import { $, els, settings, setSettings, state, DEFAULT_SETTINGS, SETTINGS_KEY } from "../state/store.js";
import { escapeHtml, escapeAttr, parseKeywordList, friendlyError } from "../utils/strings.js";
import { parseDate } from "../utils/dates.js";
import { refreshArticles } from "../features/collection.js?v=20260716-19";
import * as api from "../api/client.js?v=20260716-15";
import { refreshRuleSummaryIfNeeded } from "../features/ai-analysis.js";
import { persistAndRender } from "../features/articles.js?v=20260720-3";
import { renderAll } from "./renderers.js";
import { setStatus, showToast } from "./notifications.js?v=20260716-1";

export function populateStaticControls() {
  const options = settings.queries.map(q => `<option value="${escapeHtml(q.id)}">${escapeHtml(q.label)}</option>`).join("");
  const otherOption = `<option value="other">기타</option>`;
  els.categoryFilter.innerHTML = `<option value="all">전체 분류</option>${options}${otherOption}`;
  $("manualCategory").innerHTML = `${options}${otherOption}`;
}

export function openOverlay(id) { $(id).classList.add("open"); document.body.style.overflow = "hidden"; }
export function closeOverlay(id) { $(id).classList.remove("open"); if (!document.querySelector(".overlay.open")) document.body.style.overflow = ""; }

export function openSettings() {
  $("settingAutoRun").checked = settings.autoRun;
  $("settingYonhap").checked = settings.enableYonhap !== false;
  $("settingOpmPress").checked = settings.enableOpmPress !== false;
  $("settingMePress").checked = settings.enableMePress !== false;
  $("settingLookback").value = String(settings.lookback);
  $("settingMaxRecords").value = String(settings.maxRecords);
  $("settingCollectionLimit").value = String(settings.collectionLimit || 400);
  $("settingEndpoint").value = settings.endpoint;
  $("settingCoreKeywords").value = settings.coreKeywords.join(", ");
  $("settingRiskKeywords").value = settings.riskKeywords.join(", ");
  $("settingPositiveKeywords").value = settings.positiveKeywords.join(", ");
  $("settingExcludeKeywords").value = settings.excludeKeywords.join(", ");
  renderQuerySettings(settings.queries);
  openOverlay("settingsOverlay");
}

export function renderQuerySettings(queries) {
  const groups = [
    ["기관·평판", ["kesco_direct", "kesco_reputation"]],
    ["정부 메시지", ["presidential_message", "prime_minister_message", "climate_minister_message", "government_meeting"]],
    ["공공기관 경영", ["public_evaluation", "public_operations", "kesco_governance", "assembly_law"]],
    ["사고·안전", ["electrical_accident", "power_outage", "weather", "major_fire_breaking", "new_industry_safety"]],
    ["제도·성과·전략", ["law_standard_plan", "kesco_achievement", "strategic_trend"]],
    ["산업·거시환경", ["renewable_ess_industry", "ev_industry", "macro_economy", "ai_trend"]]
  ];
  const byId = new Map(queries.map(query => [query.id, query]));
  els.querySettings.innerHTML = groups.map(([label, ids]) => {
    const rows = ids.map(id => byId.get(id)).filter(Boolean).map(q => `<div class="query-row" data-query-id="${escapeAttr(q.id)}"><input type="checkbox" ${q.enabled ? "checked" : ""} aria-label="${escapeAttr(q.label)} 사용"><label>${escapeHtml(q.label)}</label><input type="text" value="${escapeAttr(q.query)}" aria-label="${escapeAttr(q.label)} 검색식"></div>`).join("");
    return `<section class="query-group"><h4>${escapeHtml(label)}</h4>${rows}</section>`;
  }).join("");
}

export function saveSettingsFromForm() {
  setSettings({
    ...settings,
    autoRun: $("settingAutoRun").checked,
    enableYonhap: $("settingYonhap").checked,
    enableOpmPress: $("settingOpmPress").checked,
    enableMePress: $("settingMePress").checked,
    lookback: Number($("settingLookback").value),
    maxRecords: Number($("settingMaxRecords").value),
    collectionLimit: Number($("settingCollectionLimit").value),
    endpoint: $("settingEndpoint").value.trim(),
    coreKeywords: parseKeywordList($("settingCoreKeywords").value),
    riskKeywords: parseKeywordList($("settingRiskKeywords").value),
    positiveKeywords: parseKeywordList($("settingPositiveKeywords").value),
    excludeKeywords: parseKeywordList($("settingExcludeKeywords").value),
    queries: [...els.querySettings.querySelectorAll(".query-row")].map(row => ({
      ...settings.queries.find(q => q.id === row.dataset.queryId),
      id: row.dataset.queryId,
      label: settings.queries.find(q => q.id === row.dataset.queryId)?.label || row.dataset.queryId,
      enabled: row.querySelector('input[type="checkbox"]').checked,
      query: row.querySelector('input[type="text"]').value.trim()
    }))
  });
  if (!settings.coreKeywords.length) { showToast("기관 핵심어를 한 개 이상 입력해 주세요.", "error"); return; }
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
  populateStaticControls(); closeOverlay("settingsOverlay"); renderAll(); showToast("검색 설정을 저장했습니다.", "success");
}

export function resetSettingsForm() {
  setSettings(structuredClone(DEFAULT_SETTINGS));
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
  openSettings();
  showToast("기본 검색식으로 복원했습니다.");
}

export async function restartServerFromSettings() {
  const button = $("restartServerBtn");
  const originalText = button.textContent;
  let forcedReload = null;
  try {
    button.disabled = true;
    button.textContent = "재시작 중…";
    setStatus("busy", "로컬 서버를 재시작하고 있습니다…");
    forcedReload = window.setTimeout(() => window.location.reload(), 50000);
    const result = await api.restartServer();
    closeOverlay("settingsOverlay");
    showToast("서버 재시작을 요청했습니다. 연결을 확인하고 있습니다.");
    await api.waitForRestart(result.data.processId);
    window.clearTimeout(forcedReload);
    window.location.reload();
  } catch (error) {
    if (forcedReload) window.clearTimeout(forcedReload);
    button.disabled = false;
    button.textContent = originalText;
    setStatus("error", "서버 재시작을 확인하지 못했습니다");
    showToast(`서버 재시작 실패: ${friendlyError(error)}`, "error");
  }
}

export function openArticleModal() {
  $("articleForm").reset();
  const now = new Date(); now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
  $("manualDate").value = now.toISOString().slice(0,16);
  openOverlay("articleOverlay");
  window.setTimeout(() => $("manualTitle").focus(), 30);
}

export async function addManualArticle(e) {
  e.preventDefault();
  const payload = {
    reportDate: state.date,
    title: $("manualTitle").value.trim(),
    source: $("manualSource").value.trim(),
    url: $("manualUrl").value.trim(),
    pubDate: parseDate($("manualDate").value),
    description: $("manualDescription").value.trim(),
    category: $("manualCategory").value || "kesco_direct",
    forcedRisk: "auto",
    riskKeywords: settings.riskKeywords,
    positiveKeywords: settings.positiveKeywords
  };
  try {
    const result = await api.createManualArticle(payload);
    state.demo = false;
    await refreshArticles();
    refreshRuleSummaryIfNeeded();
    closeOverlay("articleOverlay");
    persistAndRender();
    showToast(result.data.merged ? "중복 기사를 기존 항목과 합쳤습니다." : "기사를 브리핑에 추가했습니다.", "success");
  } catch (error) {
    showToast(`기사 추가 실패: ${friendlyError(error)}`, "error");
  }
}
