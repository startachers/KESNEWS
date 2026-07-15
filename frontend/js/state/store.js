import { localDateKey } from "../utils/dates.js";
import { showToast } from "../ui/notifications.js";

export const DEFAULT_SETTINGS = {
  settingsVersion: 2,
  autoRun: true,
  enableYonhap: true,
  lookback: 48,
  maxRecords: 50,
  collectionLimit: 200,
  aiModel: "gemma4:26b",
  proxy: "https://syndicate.fallible.net/feed_cors_proxy/{url}",
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
export const STORAGE_PREFIX = "kesco_media_briefing_v1_";
export const SETTINGS_KEY = "kesco_media_briefing_settings_v1";
export const LAST_AUTO_KEY = "kesco_media_briefing_last_auto_v2";
export const AI_API_BASE = location.protocol === "http:" && ["127.0.0.1", "localhost"].includes(location.hostname) && location.port === "8787" ? "/api" : "http://127.0.0.1:8787/api";
export const AI_SESSION_TOKEN = document.querySelector('meta[name="kesco-ai-token"]')?.content || new URLSearchParams(location.hash.slice(1)).get("ai") || "";

export const $ = (id) => document.getElementById(id);
export const els = {};

export function makeEmptyState(date) {
  return { date, articles: [], fetchedAt: "", lastAttemptAt: "", lastRunStatus: "idle", provider: "", preparedBy: "", summary: "", summaryEdited: false, summaryMode: "rule", summaryModel: "", summaryGeneratedAt: "", summaryInputSignature: "", summarySelectedCount: 0, summaryEvidenceIds: [], summaryEvidenceMap: [], summaryCoverage: null, summaryError: "", aiAnalysis: null, actionNote: "", demo: false, errors: [], warnings: [], duplicatesRemoved: 0, rawCollectedCount: 0 };
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
    if (!merged.proxy || merged.proxy.includes("api.allorigins.win")) merged.proxy = DEFAULT_SETTINGS.proxy;
    const direct = merged.queries.find(q => q.id === "direct");
    if (direct && !direct.query.trim().startsWith("(")) direct.query = `(${direct.query})`;
    return merged;
  } catch { return structuredClone(DEFAULT_SETTINGS); }
}

export function loadDailyState(date) {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_PREFIX + date));
    if (!saved) return makeEmptyState(date);
    return { ...makeEmptyState(date), ...saved, date, summaryMode: saved.summaryMode || (saved.summaryEdited ? "manual" : "rule"), articles: Array.isArray(saved.articles) ? saved.articles : [] };
  } catch { return makeEmptyState(date); }
}

export function saveDailyState() {
  try { localStorage.setItem(STORAGE_PREFIX + state.date, JSON.stringify(state)); }
  catch { showToast("브라우저 저장 공간이 부족해 저장하지 못했습니다.", "error"); }
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
