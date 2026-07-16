import { localDateKey } from "../utils/dates.js";
import { showToast } from "../ui/notifications.js";
import { friendlyError } from "../utils/strings.js";
import * as api from "../api/client.js";

export const DEFAULT_SETTINGS = {
  settingsVersion: 3,
  autoRun: true,
  enableYonhap: true,
  lookback: 48,
  maxRecords: 50,
  collectionLimit: 400,
  aiModel: "gemma4:26b",
  endpoint: "",
  coreKeywords: ["한국전기안전공사", "전기안전공사", "KESCO"],
  riskKeywords: ["사망", "중대재해", "압수수색", "감사", "국정감사", "화재", "감전", "사고", "논란", "위반", "고발", "부실", "해킹", "정전", "피해", "징계"],
  positiveKeywords: ["수상", "협약", "성과", "혁신", "봉사", "지원", "캠페인", "예방", "확대", "우수", "개선", "안전문화"],
  excludeKeywords: ["채용공고"],
  queries: [
    { id: "kesco_direct", label: "공사 직접 보도", enabled: true, query: '("한국전기안전공사" OR "전기안전공사" OR "KESCO")' },
    { id: "kesco_reputation", label: "공사 위기·평판", enabled: true, query: '("한국전기안전공사" OR "전기안전공사" OR "KESCO") (사망 OR 사고 OR 화재 OR 감전 OR 정전 OR 중대재해 OR 부실점검 OR 허위점검 OR 위반 OR 논란 OR 수사 OR 고발 OR 압수수색 OR 징계 OR 비위 OR 해킹 OR "정보 유출" OR 민원)' },
    { id: "presidential_message", label: "대통령·대통령실 메시지", enabled: true, query: '("대통령실" OR "대통령"{OR_current_president}) ("전기안전" OR 전력망 OR 전력수급 OR 전기설비 OR 전기화재 OR 감전 OR 정전 OR ESS OR "전기차 충전") (지시 OR 주문 OR 당부 OR 강조 OR 브리핑 OR 업무보고 OR 대책)' },
    { id: "prime_minister_message", label: "국무총리·총리실 메시지", enabled: true, query: '("국무총리" OR "총리실" OR "국무조정실"{OR_current_prime_minister}) ("전기안전" OR 전력망 OR 전력수급 OR 전기설비 OR 전기화재 OR 감전 OR 정전) (지시 OR 주문 OR 당부 OR 강조 OR 회의 OR 현안조정 OR 대책)' },
    { id: "climate_minister_message", label: "기후에너지환경부 장관 메시지", enabled: true, query: '("기후에너지환경부"{OR_current_climate_minister}) (전기안전 OR 전력망 OR 전력수급 OR 전기설비 OR 전기화재 OR 감전 OR 정전 OR ESS OR "전기차 충전" OR 재생에너지) (발언 OR 지시 OR 주문 OR 당부 OR 브리핑 OR 업무보고 OR 현장점검 OR 대책)' },
    { id: "government_meeting", label: "국무회의·관계장관회의·정부위원회", enabled: true, query: '("국무회의" OR "국정현안관계장관회의" OR "경제관계장관회의" OR "공공기관운영위원회" OR "에너지위원회" OR "전력정책심의회") (전기안전 OR 전력 OR 전력망 OR 전력수급 OR 전기설비 OR 정전 OR 공공기관)' },
    { id: "public_evaluation", label: "공공기관 경영평가", enabled: true, query: '("공공기관 경영실적 평가" OR "공공기관 경영평가" OR "경영평가편람" OR "경영평가 결과" OR "경영실적 평가결과")' },
    { id: "public_operations", label: "공공기관 운영정책", enabled: true, query: '("공공기관" OR "공기업" OR "준정부기관") ("공공기관운영위원회" OR "예산운용지침" OR 총인건비 OR 직무급 OR 성과급 OR "안전관리등급" OR 경영공시 OR ALIO)' },
    { id: "kesco_governance", label: "공사 경영·거버넌스", enabled: true, query: '("한국전기안전공사" OR "전기안전공사" OR "KESCO") (경영평가 OR 경영공시 OR 국정감사 OR 감사원 OR 이사회 OR 기관장 OR 사장 OR 상임감사 OR 임원 OR 인사 OR 노사 OR 노조 OR 파업 OR 예산 OR 총인건비 OR 직무급 OR 성과급)' },
    { id: "assembly_law", label: "국회·국정감사·법안", enabled: true, query: '(국회 OR 국정감사 OR 국정조사 OR 법안 OR 개정안 OR 입법예고 OR 현안질의) (전기안전 OR 전기화재 OR 감전 OR 정전 OR 전력망 OR 전기설비 OR "한국전기안전공사")' },
    { id: "electrical_accident", label: "전기화재·감전 사고", enabled: true, query: '("전기화재" OR "전기 화재" OR "누전 화재" OR "전기적 요인" OR "감전사고" OR "감전 사고" OR "감전 사망" OR "배전반 화재" OR "변압기 화재")' },
    { id: "power_outage", label: "정전·전력공급 장애", enabled: true, query: '("대규모 정전" OR "광역 정전" OR "일대 정전" OR "전력 공급 중단" OR "전력망 장애" OR "계통 장애" OR 블랙아웃 OR "변전소 고장" OR "송전선로 고장" OR "배전선로 고장")' },
    { id: "major_fire_breaking", label: "중대화재·원인 미상 속보", enabled: true, query: '(화재 OR 폭발 OR 큰불) (사망 OR 숨져 OR 사상 OR 중상 OR 심정지 OR 실종 OR 전소 OR 대피 OR "대응 1단계" OR "대응 2단계" OR "대응 3단계")' },
    { id: "new_industry_safety", label: "ESS·배터리·충전시설 등 신산업 설비안전", enabled: true, query: '(ESS OR "에너지저장장치" OR 배터리 OR "전기차 충전") (화재 OR 감전 OR 폭발 OR 사고 OR 안전점검 OR 결함 OR 리콜)' },
    { id: "law_standard_plan", label: "법령·기준·기본계획", enabled: true, query: '("전기안전관리법" OR "전기사업법" OR "한국전기설비규정" OR KEC OR "전기설비기술기준" OR "전기안전관리 기본계획" OR "전력수급기본계획") (개정 OR 시행 OR 입법예고 OR 행정예고 OR 고시 OR 확정 OR 발표)' },
    { id: "kesco_achievement", label: "공사 성과·상생·예방활동", enabled: true, query: '("한국전기안전공사" OR "전기안전공사" OR "KESCO") (업무협약 OR 협약 OR 수상 OR 혁신 OR 합동점검 OR 특별점검 OR 예방점검 OR 캠페인 OR 봉사 OR 기부 OR 상생 OR 안전문화 OR 취약계층)' },
    { id: "strategic_trend", label: "전력망·분산에너지·데이터센터 등 전략동향", enabled: true, query: '("전력망" OR "송전망" OR "배전망" OR "분산에너지" OR "데이터센터" OR "재생에너지" OR "전력수요") (전기안전 OR 안전관리 OR 전기설비 OR 화재 OR 정전 OR 검사 OR 규제 OR 기본계획)' }
  ]
};

export const CATEGORY_COLORS = {
  kesco_direct: "#326c9c", kesco_reputation: "#9f3434", presidential_message: "#6548a6",
  prime_minister_message: "#7654ad", climate_minister_message: "#087f76", government_meeting: "#536b92",
  public_evaluation: "#b46a12", public_operations: "#9a7218", kesco_governance: "#8b5a2b",
  assembly_law: "#596481", electrical_accident: "#b64242", power_outage: "#b0533f",
  major_fire_breaking: "#8f3030", new_industry_safety: "#b05c75", law_standard_plan: "#70539b",
  kesco_achievement: "#087f76", strategic_trend: "#397b62"
};
export const RISK_LABELS = { critical: "긴급", watch: "주의", routine: "일상" };
export const SENTIMENT_LABELS = { positive: "긍정", neutral: "중립", negative: "부정" };
export const SETTINGS_KEY = "kesco_media_briefing_settings_v1";
export const LAST_AUTO_KEY = "kesco_media_briefing_last_auto_v2";
export const AI_API_BASE = location.protocol === "http:" && ["127.0.0.1", "localhost"].includes(location.hostname) && location.port === "8787" ? "/api" : "http://127.0.0.1:8787/api";
export const AI_SESSION_TOKEN = document.querySelector('meta[name="kesco-ai-token"]')?.content || new URLSearchParams(location.hash.slice(1)).get("ai") || "";

export const $ = (id) => document.getElementById(id);
export const els = {};

export function makeEmptyState(date) {
  return { date, revision: 0, status: "draft", latestFinalVersion: null, finalizedAt: null, articles: [], issues: [], fetchedAt: "", lastAttemptAt: "", lastRunStatus: "idle", provider: "", preparedBy: "", summary: "", summaryEdited: false, summaryMode: "rule", summaryModel: "", summaryGeneratedAt: "", summaryInputSignature: "", summaryContextLength: 0, summarySelectedCount: 0, summaryEvidenceIds: [], summaryEvidenceMap: [], summaryCoverage: null, summaryError: "", aiStale: false, aiAnalysis: null, aiRunId: "", aiRunStatus: "idle", actionNote: "", demo: false, errors: [], warnings: [], duplicatesRemoved: 0, rawCollectedCount: 0, sourceFilterStats: null };
}

export function loadSettings() {
  try {
    const saved = JSON.parse(localStorage.getItem(SETTINGS_KEY));
    if (!saved) return structuredClone(DEFAULT_SETTINGS);
    const merged = { ...structuredClone(DEFAULT_SETTINGS), ...saved, queries: Array.isArray(saved.queries) ? saved.queries : structuredClone(DEFAULT_SETTINGS.queries) };
    if (Number(saved.settingsVersion || 0) < DEFAULT_SETTINGS.settingsVersion) {
      const savedById = new Map((Array.isArray(saved.queries) ? saved.queries : []).map(query => [query.id, query]));
      merged.queries = structuredClone(DEFAULT_SETTINGS.queries).map(query => ({
        ...query,
        enabled: savedById.has(query.id) ? savedById.get(query.id).enabled !== false : query.enabled
      }));
      merged.settingsVersion = DEFAULT_SETTINGS.settingsVersion;
      localStorage.setItem(SETTINGS_KEY, JSON.stringify(merged));
      settingsMigrationNotice = true;
    }
    delete merged.proxy;
    return merged;
  } catch { return structuredClone(DEFAULT_SETTINGS); }
}

let settingsMigrationNotice = false;

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
    const [articlesResult, issuesResult, latestCollectionResult] = await Promise.all([
      api.listArticles(date, false),
      api.listIssues(date),
      api.getLatestCollection(date).catch(error => {
        if (error.code === "COLLECTION_FAILED") return null;
        throw error;
      }),
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
      actionNote: briefing.actionNote || "",
      fetchedAt: latestCollectionResult?.data?.finishedAt || "",
      lastAttemptAt: latestCollectionResult?.data?.startedAt || "",
      lastRunStatus: latestCollectionResult?.data?.status === "failed" ? "error" : latestCollectionResult ? "success" : "idle",
      provider: latestCollectionResult?.data?.providers?.map(item => item.provider).filter(Boolean).join(" + ") || "",
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
