import { localDateKey } from "../utils/dates.js";
import { showToast } from "../ui/notifications.js?v=20260716-1";
import { friendlyError } from "../utils/strings.js";
import * as api from "../api/client.js";

export const DEFAULT_SETTINGS = {
  autoRun: true,
  aiModel: "gemma4:31b",
  settingsVersion: 0,
  enableYonhap: false,
  enableOpmPress: false,
  enableMePress: false,
  lookback: 24,
  maxRecords: 50,
  collectionLimit: 400,
  endpoint: "",
  coreKeywords: [],
  riskKeywords: [],
  positiveKeywords: [],
  excludeKeywords: [],
  queries: []
};
export const CATEGORY_COLORS = {
  kesco_direct: "#326c9c", kesco_reputation: "#9f3434", presidential_message: "#6548a6",
  prime_minister_message: "#7654ad", climate_minister_message: "#087f76", government_meeting: "#536b92",
  public_evaluation: "#b46a12", public_operations: "#9a7218", kesco_governance: "#8b5a2b",
  assembly_law: "#596481", electrical_accident: "#b64242", power_outage: "#b0533f", weather: "#28708f",
  major_fire_breaking: "#8f3030", new_industry_safety: "#b05c75", law_standard_plan: "#70539b",
  kesco_achievement: "#087f76", strategic_trend: "#397b62", renewable_ess_industry: "#247a73",
  ev_industry: "#2f6fa3", macro_economy: "#9a6a20", ai_trend: "#5364a8"
};
export const SENTIMENT_LABELS = { positive: "긍정", neutral: "중립", negative: "부정" };
export const SETTINGS_KEY = "kesco_media_briefing_settings_v1";
export const LAST_AUTO_KEY = "kesco_media_briefing_last_auto_v2";
// FastAPI가 화면과 API를 함께 제공하므로 HTTP(S)에서는 항상 같은 출처를 사용한다.
// file://로 직접 연 레거시 사용 방식만 로컬 운영 서버로 연결한다.
export const AI_API_BASE = ["http:", "https:"].includes(location.protocol)
  ? "/api"
  : "http://127.0.0.1:8787/api";
export const AI_SESSION_TOKEN = document.querySelector('meta[name="kesco-ai-token"]')?.content || new URLSearchParams(location.hash.slice(1)).get("ai") || "";

export const $ = (id) => document.getElementById(id);
export const els = {};

export function makeEmptyState(date) {
  return { date, revision: 0, status: "draft", latestFinalVersion: null, finalizedAt: null, articles: [], issues: [], weather: { configured: false, latestContext: null, attached: null, attachedContext: null, newerContextAvailable: false, latestRun: null }, weatherLoading: false, weatherRegionId: "national", fetchedAt: "", lastAttemptAt: "", lastRunStatus: "idle", provider: "", naverStatus: "네이버 뉴스 API 미설정", preparedBy: "", summary: "", summaryEdited: false, summaryMode: "rule", summaryModel: "", summaryGeneratedAt: "", summaryInputSignature: "", summaryContextLength: 0, summarySelectedCount: 0, summaryEvidenceIds: [], summaryEvidenceMap: [], summaryCoverage: null, summaryError: "", aiStale: false, aiAnalysis: null, aiValidationWarnings: [], aiRunId: "", aiRunStatus: "idle", actionNote: "", demo: false, errors: [], warnings: [], duplicatesRemoved: 0, rawCollectedCount: 0, sourceFilterStats: null };
}

let legacyServerSettings = null;

export function loadSettings() {
  try {
    const saved = JSON.parse(localStorage.getItem(SETTINGS_KEY));
    if (!saved) return structuredClone(DEFAULT_SETTINGS);
    if (Array.isArray(saved.queries) || Array.isArray(saved.coreKeywords)) {
      legacyServerSettings = saved;
      settingsMigrationNotice = true;
    }
    const local = {
      ...structuredClone(DEFAULT_SETTINGS),
      autoRun: saved.autoRun !== false,
      aiModel: saved.aiModel || DEFAULT_SETTINGS.aiModel
    };
    localStorage.setItem(SETTINGS_KEY, JSON.stringify({ autoRun: local.autoRun, aiModel: local.aiModel }));
    return local;
  } catch { return structuredClone(DEFAULT_SETTINGS); }
}

let settingsMigrationNotice = false;

export function saveLocalSettings() {
  localStorage.setItem(SETTINGS_KEY, JSON.stringify({
    autoRun: settings.autoRun !== false,
    aiModel: settings.aiModel || DEFAULT_SETTINGS.aiModel
  }));
}

export async function loadServerSettings() {
  let result = await api.getSettings();
  const local = { autoRun: settings.autoRun, aiModel: settings.aiModel };
  if (!result.meta?.hasOverride && legacyServerSettings) {
    const defaults = result.data;
    const migrated = {
      ...defaults,
      lookback: 24,
      maxRecords: Number(legacyServerSettings.maxRecords || defaults.maxRecords),
      collectionLimit: Number(legacyServerSettings.collectionLimit || defaults.collectionLimit),
      enableYonhap: legacyServerSettings.enableYonhap !== false,
      enableOpmPress: legacyServerSettings.enableOpmPress !== false,
      enableMePress: legacyServerSettings.enableMePress !== false,
      endpoint: String(legacyServerSettings.endpoint || ""),
      coreKeywords: Array.isArray(legacyServerSettings.coreKeywords) ? legacyServerSettings.coreKeywords : defaults.coreKeywords,
      riskKeywords: Array.isArray(legacyServerSettings.riskKeywords) ? legacyServerSettings.riskKeywords : defaults.riskKeywords,
      positiveKeywords: Array.isArray(legacyServerSettings.positiveKeywords) ? legacyServerSettings.positiveKeywords : defaults.positiveKeywords,
      excludeKeywords: Array.isArray(legacyServerSettings.excludeKeywords) ? legacyServerSettings.excludeKeywords : defaults.excludeKeywords,
      queries: defaults.queries.map(query => {
        const saved = legacyServerSettings.queries?.find(item => item.id === query.id);
        return saved ? { ...query, enabled: saved.enabled !== false, query: saved.query || query.query } : query;
      })
    };
    result = await api.putSettings(migrated);
    legacyServerSettings = null;
  }
  setSettings({ ...result.data, ...local });
  return settings;
}

export function consumeSettingsMigrationNotice() {
  const shouldNotify = settingsMigrationNotice;
  settingsMigrationNotice = false;
  return shouldNotify;
}

export async function loadDailyState(date) {
  try {
    let briefing;
    try {
      briefing = (await api.getBriefing(date)).data;
    } catch (error) {
      if (error.code === "BRIEFING_NOT_FOUND") briefing = (await api.putBriefing(date, 0, {})).data;
      else throw error;
    }
    const [articlesResult, issuesResult, latestCollectionResult, weatherResult] = await Promise.all([
      api.listArticles(date, false),
      api.listIssues(date),
      api.getLatestCollection(date).catch(error => {
        if (error.code === "COLLECTION_FAILED") return null;
        throw error;
      }),
      api.getWeatherBriefing(date),
    ]);
    const articles = articlesResult.data.articles.map(a => ({ ...a, isDemo: false }));
    const successfulRun = briefing.aiState?.lastSuccessfulRun;
    const latestRun = briefing.aiState?.latestRun;
    const analysis = successfulRun?.response?.analysis || null;
    const evidenceArticles = successfulRun?.request?.articles || [];
    const collectionProviders = latestCollectionResult?.data?.providers || [];
    const naverProviders = collectionProviders.filter(item => item.provider === "네이버 뉴스 API");
    const naverStatus = !naverProviders.length
      ? "네이버 뉴스 API 미설정"
      : naverProviders.some(item => item.status === "failed")
        ? "네이버 뉴스 API 오류"
        : "네이버 뉴스 API 연결됨";
    return {
      ...makeEmptyState(date),
      articles,
      issues: issuesResult.data.issues || [],
      weather: weatherResult.data,
      revision: briefing.revision,
      status: briefing.status || "draft",
      latestFinalVersion: briefing.latestFinalVersion,
      finalizedAt: briefing.finalizedAt,
      preparedBy: briefing.preparedBy || "",
      summary: briefing.situationSummary || "",
      summaryEdited: briefing.summaryMode === "manual" || briefing.summaryMode === "ai-edited",
      summaryMode: briefing.summaryMode || "rule",
      summaryModel: briefing.aiModel || "",
      summaryGeneratedAt: briefing.aiGeneratedAt || "",
      summaryInputSignature: briefing.aiInputSignature || "",
      summaryContextLength: successfulRun?.request?.contextLength || 0,
      summarySelectedCount: evidenceArticles.length,
      summaryEvidenceIds: Object.keys(successfulRun?.evidence || {}),
      summaryEvidenceMap: evidenceArticles.map(article => ({ id: article.id, title: article.title, source: article.source, basis: article.bodyStatus, error: article.bodyError || "" })),
      summaryCoverage: successfulRun ? {
        selected: evidenceArticles.length,
        bodyCount: evidenceArticles.filter(article => article.bodyStatus === "full_text").length,
        rssOnlyCount: evidenceArticles.filter(article => article.bodyStatus === "summary_only").length,
        titleOnlyCount: evidenceArticles.filter(article => article.bodyStatus === "missing" && !article.bodyError).length,
        failedCount: evidenceArticles.filter(article => article.bodyError).length
      } : null,
      summaryError: briefing.aiState?.currentError ? `최근 AI 실행 실패: ${briefing.aiState.currentError} · 마지막 정상 결과는 유지됩니다.` : "",
      aiStale: !!successfulRun?.stale,
      aiAnalysis: analysis,
      aiValidationWarnings: successfulRun?.response?.validationWarnings || [],
      aiRunId: latestRun?.id || "",
      aiRunStatus: latestRun?.status || "idle",
      actionNote: briefing.actionNote || "",
      fetchedAt: latestCollectionResult?.data?.finishedAt || "",
      lastAttemptAt: latestCollectionResult?.data?.startedAt || "",
      lastRunStatus: latestCollectionResult?.data?.status === "failed" ? "error" : latestCollectionResult ? "success" : "idle",
      provider: [...new Set(collectionProviders.map(item => item.provider).filter(Boolean))].join(" + "),
      naverStatus,
      rawCollectedCount: latestCollectionResult?.data?.rawCount || 0,
      sourceFilterStats: latestCollectionResult?.data?.source_filter_stats || null
    };
  } catch (error) {
    showToast(`${date} 저장본을 불러오지 못했습니다: ${friendlyError(error)}`, "error");
    return makeEmptyState(date);
  }
}

let saveTimer = null;
let savePromise = Promise.resolve();

async function persistScalarState() {
  if (state.status === "final") return;
  const result = await api.putBriefing(state.date, state.revision, {
    preparedBy: state.preparedBy,
    situationSummary: state.summary,
    actionNote: state.actionNote,
    summaryMode: state.summaryMode,
    aiModel: state.summaryModel,
    aiGeneratedAt: state.summaryGeneratedAt,
    aiInputSignature: state.summaryInputSignature
  });
  state.revision = result.data.revision;
}

function queueScalarSave() {
  savePromise = savePromise.catch(() => {}).then(persistScalarState).catch(error => {
    if (error.code === "BRIEFING_REVISION_CONFLICT") {
      showToast("다른 화면에서 브리핑이 변경되었습니다. 새로고침 후 다시 시도해 주세요.", "error");
    } else {
      showToast(`저장 실패: ${friendlyError(error)}`, "error");
    }
    throw error;
  });
  return savePromise;
}

/** briefing 작업본의 스칼라 필드(요약·지시사항·담당자·AI 모델 등)만 저장한다.
 * 기사별 선택·중요·메모는 features/articles.js의 patchArticle*이 개별 PATCH로 저장한다. */
export function saveDailyState() {
  if (state.status === "final") return;
  if (saveTimer) window.clearTimeout(saveTimer);
  saveTimer = window.setTimeout(() => { saveTimer = null; queueScalarSave().catch(() => {}); }, 500);
}

export function flushDailyState() {
  if (saveTimer) window.clearTimeout(saveTimer);
  saveTimer = null;
  return queueScalarSave();
}

export let settings = loadSettings();
export let state = makeEmptyState(localDateKey());
export let filters = { text: "", category: "all", risk: "all", selection: "all", sort: "review" };
export let isSearching = false;
export let isAnalyzingSummary = false;
export let aiRequestSerial = 0;
export let aiAbortController = null;
export let aiServerState = { checking: true, online: false, models: [], defaultModel: "", error: "" };

export function setSettings(next) { settings = next; }
export function setState(next) { state = next; }
export function setFilters(next) { filters = next; }
export function setSearching(value) { isSearching = value; }
export function setAnalyzingSummary(value) { isAnalyzingSummary = value; }
export function nextAiRequestSerial() { aiRequestSerial += 1; return aiRequestSerial; }
export function setAiAbortController(value) { aiAbortController = value; }
export function setAiServerState(next) { aiServerState = next; }
