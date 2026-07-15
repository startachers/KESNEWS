import { localDateKey } from "../utils/dates.js";
import { showToast } from "../ui/notifications.js";
import { friendlyError } from "../utils/strings.js";
import * as api from "../api/client.js";

export const DEFAULT_SETTINGS = {
  settingsVersion: 2,
  autoRun: true,
  enableYonhap: true,
  lookback: 48,
  maxRecords: 50,
  collectionLimit: 200,
  aiModel: "gemma4:26b",
  endpoint: "",
  coreKeywords: ["한국전기안전공사", "전기안전공사", "KESCO"],
  riskKeywords: ["사망", "중대재해", "압수수색", "감사", "국정감사", "화재", "감전", "사고", "논란", "위반", "고발", "부실", "해킹", "정전", "피해", "징계"],
  positiveKeywords: ["수상", "협약", "성과", "혁신", "봉사", "지원", "캠페인", "예방", "확대", "우수", "개선", "안전문화"],
  excludeKeywords: ["채용공고"],
  queries: [
    { id: "direct", label: "기관 직접", enabled: true, query: '("한국전기안전공사" OR "전기안전공사" OR "KESCO")' },
    { id: "safety", label: "전기화재·감전", enabled: true, query: '("전기화재" OR "전기 화재" OR "감전사고" OR "감전 사고")' },
    { id: "policy", label: "기후·에너지 정책", enabled: true, query: '"기후에너지환경부" (에너지 OR 전기)' },
    { id: "management", label: "경영·감사", enabled: true, query: '("한국전기안전공사" OR "전기안전공사") (사장 OR 감사 OR 국정감사 OR 경영평가 OR 인사)' },
    { id: "community", label: "지역·상생", enabled: true, query: '("한국전기안전공사" OR "전기안전공사") (협약 OR 봉사 OR 지원 OR 캠페인 OR 지역)' },
    { id: "industry", label: "재생에너지", enabled: true, query: '("재생에너지" OR "신재생에너지")' }
  ]
};

export const CATEGORY_COLORS = { direct: "#326c9c", safety: "#b64242", policy: "#70539b", management: "#c97a16", community: "#087f76", industry: "#397b62" };
export const RISK_LABELS = { critical: "긴급", watch: "주의", routine: "일상" };
export const SENTIMENT_LABELS = { positive: "긍정", neutral: "중립", negative: "부정" };
export const SETTINGS_KEY = "kesco_media_briefing_settings_v1";
export const LAST_AUTO_KEY = "kesco_media_briefing_last_auto_v2";
export const AI_API_BASE = location.protocol === "http:" && ["127.0.0.1", "localhost"].includes(location.hostname) && location.port === "8787" ? "/api" : "http://127.0.0.1:8787/api";
export const AI_SESSION_TOKEN = document.querySelector('meta[name="kesco-ai-token"]')?.content || new URLSearchParams(location.hash.slice(1)).get("ai") || "";

export const $ = (id) => document.getElementById(id);
export const els = {};

export function makeEmptyState(date) {
  return { date, revision: 0, status: "draft", latestFinalVersion: null, finalizedAt: null, articles: [], issues: [], fetchedAt: "", lastAttemptAt: "", lastRunStatus: "idle", provider: "", preparedBy: "", summary: "", summaryEdited: false, summaryMode: "rule", summaryModel: "", summaryGeneratedAt: "", summaryInputSignature: "", summaryContextLength: 0, summarySelectedCount: 0, summaryEvidenceIds: [], summaryEvidenceMap: [], summaryCoverage: null, summaryError: "", aiStale: false, aiAnalysis: null, aiRunId: "", aiRunStatus: "idle", actionNote: "", demo: false, errors: [], warnings: [], duplicatesRemoved: 0, rawCollectedCount: 0 };
}

export function loadSettings() {
  try {
    const saved = JSON.parse(localStorage.getItem(SETTINGS_KEY));
    if (!saved) return structuredClone(DEFAULT_SETTINGS);
    const merged = { ...structuredClone(DEFAULT_SETTINGS), ...saved, queries: Array.isArray(saved.queries) ? saved.queries : structuredClone(DEFAULT_SETTINGS.queries) };
    if (Number(saved.settingsVersion || 0) < DEFAULT_SETTINGS.settingsVersion) {
      const savedById = new Map((Array.isArray(saved.queries) ? saved.queries : []).map(query => [query.id, query]));
      merged.maxRecords = Math.min(100, Math.max(50, Number(saved.maxRecords || 0)));
      merged.collectionLimit = Math.max(200, Number(saved.collectionLimit || 0));
      merged.queries = structuredClone(DEFAULT_SETTINGS.queries).map(query => ({
        ...query,
        enabled: savedById.has(query.id) ? savedById.get(query.id).enabled !== false : query.enabled
      }));
      merged.settingsVersion = DEFAULT_SETTINGS.settingsVersion;
      localStorage.setItem(SETTINGS_KEY, JSON.stringify(merged));
    }
    delete merged.proxy;
    const direct = merged.queries.find(q => q.id === "direct");
    if (direct && !direct.query.trim().startsWith("(")) direct.query = `(${direct.query})`;
    return merged;
  } catch { return structuredClone(DEFAULT_SETTINGS); }
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
    const [articlesResult, issuesResult] = await Promise.all([
      api.listArticles(date, false),
      api.listIssues(date),
    ]);
    const articles = articlesResult.data.articles.map(a => ({ ...a, isDemo: false }));
    const successfulRun = briefing.aiState?.lastSuccessfulRun;
    const latestRun = briefing.aiState?.latestRun;
    const analysis = successfulRun?.response?.analysis || null;
    const evidenceArticles = successfulRun?.request?.articles || [];
    return {
      ...makeEmptyState(date),
      articles,
      issues: issuesResult.data.issues || [],
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
      aiRunId: latestRun?.id || "",
      aiRunStatus: latestRun?.status || "idle",
      actionNote: briefing.actionNote || ""
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
export let filters = { text: "", category: "all", risk: "all", selection: "all", sort: "relevance" };
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
