import { $, els, settings, setSettings, state, DEFAULT_SETTINGS, SETTINGS_KEY } from "../state/store.js";
import { escapeHtml, escapeAttr, parseKeywordList, uid } from "../utils/strings.js";
import { parseDate } from "../utils/dates.js";
import { classifyArticle, deduplicateDetailed } from "../features/collection.js";
import { refreshRuleSummaryIfNeeded } from "../features/ai-analysis.js";
import { persistAndRender } from "../features/articles.js";
import { renderAll } from "./renderers.js";
import { showToast } from "./notifications.js";

export function populateStaticControls() {
  const options = settings.queries.map(q => `<option value="${escapeHtml(q.id)}">${escapeHtml(q.label)}</option>`).join("");
  els.categoryFilter.innerHTML = `<option value="all">전체 분류</option>${options}`;
  $("manualCategory").innerHTML = options;
}

export function openOverlay(id) { $(id).classList.add("open"); document.body.style.overflow = "hidden"; }
export function closeOverlay(id) { $(id).classList.remove("open"); if (!document.querySelector(".overlay.open")) document.body.style.overflow = ""; }

export function openSettings() {
  $("settingAutoRun").checked = settings.autoRun;
  $("settingYonhap").checked = settings.enableYonhap !== false;
  $("settingLookback").value = String(settings.lookback);
  $("settingMaxRecords").value = String(settings.maxRecords);
  $("settingCollectionLimit").value = String(settings.collectionLimit || 200);
  $("settingEndpoint").value = settings.endpoint;
  $("settingCoreKeywords").value = settings.coreKeywords.join(", ");
  $("settingRiskKeywords").value = settings.riskKeywords.join(", ");
  $("settingPositiveKeywords").value = settings.positiveKeywords.join(", ");
  $("settingExcludeKeywords").value = settings.excludeKeywords.join(", ");
  renderQuerySettings(settings.queries);
  openOverlay("settingsOverlay");
}

export function renderQuerySettings(queries) {
  els.querySettings.innerHTML = queries.map(q => `<div class="query-row" data-query-id="${escapeAttr(q.id)}"><input type="checkbox" ${q.enabled ? "checked" : ""} aria-label="${escapeAttr(q.label)} 사용"><label>${escapeHtml(q.label)}</label><input type="text" value="${escapeAttr(q.query)}" aria-label="${escapeAttr(q.label)} 검색식"></div>`).join("");
}

export function saveSettingsFromForm() {
  setSettings({
    ...settings,
    autoRun: $("settingAutoRun").checked,
    enableYonhap: $("settingYonhap").checked,
    lookback: Number($("settingLookback").value),
    maxRecords: Number($("settingMaxRecords").value),
    collectionLimit: Number($("settingCollectionLimit").value),
    endpoint: $("settingEndpoint").value.trim(),
    coreKeywords: parseKeywordList($("settingCoreKeywords").value),
    riskKeywords: parseKeywordList($("settingRiskKeywords").value),
    positiveKeywords: parseKeywordList($("settingPositiveKeywords").value),
    excludeKeywords: parseKeywordList($("settingExcludeKeywords").value),
    queries: [...els.querySettings.querySelectorAll(".query-row")].map(row => ({
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

export function openArticleModal() {
  $("articleForm").reset();
  const now = new Date(); now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
  $("manualDate").value = now.toISOString().slice(0,16);
  openOverlay("articleOverlay");
  window.setTimeout(() => $("manualTitle").focus(), 30);
}

export function addManualArticle(e) {
  e.preventDefault();
  const raw = {
    id: uid(), title: $("manualTitle").value.trim(), source: $("manualSource").value.trim(),
    url: $("manualUrl").value.trim(), pubDate: parseDate($("manualDate").value), description: $("manualDescription").value.trim(),
    category: $("manualCategory").value || "direct", manual: true
  };
  let article = classifyArticle(raw);
  const forcedRisk = $("manualRisk").value;
  if (forcedRisk !== "auto") { article.risk = forcedRisk; article.sentiment = forcedRisk === "routine" ? article.sentiment : "negative"; }
  const result = deduplicateDetailed([article, ...state.articles.filter(item => !item.isDemo)]);
  state.articles = result.items; state.demo = false;
  state.duplicatesRemoved = (state.duplicatesRemoved || 0) + result.removed;
  refreshRuleSummaryIfNeeded();
  closeOverlay("articleOverlay"); persistAndRender();
  showToast(result.removed ? "중복 기사를 기존 항목과 합쳤습니다." : "기사를 브리핑에 추가했습니다.", "success");
}
