import { state, settings, LAST_AUTO_KEY, setSearching, isSearching, saveDailyState } from "../state/store.js";
import { localDateKey, dateValue } from "../utils/dates.js";
import { cleanText, shortText, friendlyError, safeUrl } from "../utils/strings.js";
import * as api from "../api/client.js";
import { showToast, setStatus, setSearchButton } from "../ui/notifications.js";
import { renderSidePanel, renderAll } from "../ui/renderers.js";
import { refreshRuleSummaryIfNeeded } from "./ai-analysis.js";

export async function refreshArticles() {
  const result = await api.listArticles(state.date, false);
  const { articles, meta } = result.data;
  state.articles = articles.map(a => ({ ...a, isDemo: false }));
  if (meta?.failedProviders?.length) {
    const notice = `이전 수집에서 실패한 provider: ${meta.failedProviders.join(", ")}`;
    if (!state.warnings.includes(notice)) state.warnings = [...state.warnings, notice];
  }
}

export async function runSearch(auto = false) {
  if (state.status === "final") {
    if (!auto) showToast("최종 확정된 작업본입니다. 수정 재개 후 기사를 검색해 주세요.", "error");
    return;
  }
  if (isSearching) return;
  if (state.date !== localDateKey() && auto) return;
  const enabled = settings.queries.filter(q => q.enabled && q.query.trim());
  if (!enabled.length && !settings.enableYonhap) { showToast("활성화된 검색식이나 뉴스 수집원이 없습니다. 설정을 확인해 주세요.", "error"); return; }
  setSearching(true);
  state.demo = false;
  setSearchButton(true);
  setStatus("busy", `연합뉴스 우선 · ${enabled.length}개 검색식으로 기사를 찾는 중…`);
  renderSidePanel();

  state.lastAttemptAt = new Date().toISOString();
  try {
    const result = await requestCollection({
      reportDate: state.date,
      lookbackHours: Number(settings.lookback),
      maxRecordsPerQuery: Number(settings.maxRecords),
      collectionLimit: Number(settings.collectionLimit || 200),
      enableYonhap: !!settings.enableYonhap,
      queries: enabled.map(q => ({ id: q.id, label: q.label, query: q.query })),
      coreKeywords: settings.coreKeywords,
      riskKeywords: settings.riskKeywords,
      positiveKeywords: settings.positiveKeywords,
      excludeKeywords: settings.excludeKeywords,
      endpoint: settings.endpoint
    });

    state.fetchedAt = result.fetchedAt || state.lastAttemptAt;
    state.provider = result.provider || "";
    state.rawCollectedCount = result.rawCollectedCount || 0;
    state.duplicatesRemoved = result.duplicatesRemoved || 0;
    state.warnings = result.warnings || [];

    if (result.status !== "failed") {
      await refreshArticles();
      state.demo = false;
      state.lastRunStatus = "success";
      state.errors = [];
      localStorage.setItem(LAST_AUTO_KEY, localDateKey());
      state.summaryError = "";
      refreshRuleSummaryIfNeeded();

      if (state.articles.length) {
        setStatus("live", `${state.articles.length}건 정리 · 중복 ${state.duplicatesRemoved}건 제거`);
        showToast(`${state.articles.length}건을 정리하고 중복 ${state.duplicatesRemoved}건을 제거했습니다.${state.warnings.length ? ` 일부 검색 ${state.warnings.length}건은 보조 처리했습니다.` : ""}`, state.warnings.length ? "" : "success");
      } else {
        setStatus("idle", "검색 기간 내 관련 기사가 없습니다");
        showToast("수집 연결은 정상이지만 검색 기간 내 관련 기사가 없습니다.");
      }
    } else {
      state.lastRunStatus = "error";
      state.errors = result.errors?.length ? result.errors : ["데이터 제공 경로에서 응답을 받지 못했습니다."];
      localStorage.removeItem(LAST_AUTO_KEY);
      setStatus("error", "기사 수집 실패 · 오류 상세를 확인하세요");
      showToast(`수집 실패: ${shortText(state.errors[0], 120)}`, "error");
    }
    saveDailyState();
  } catch (error) {
    state.lastRunStatus = "error";
    state.errors = [friendlyError(error)];
    localStorage.removeItem(LAST_AUTO_KEY);
    saveDailyState();
    setStatus("error", "기사 검색을 완료하지 못했습니다");
    showToast(friendlyError(error), "error");
  } finally {
    setSearching(false);
    setSearchButton(false);
    renderAll();
  }
}

async function requestCollection(payload) {
  const response = await api.runCollection(payload);
  return response.data;
}

export function normalizedArticleTitle(value) {
  return cleanText(value || "").normalize("NFKC").toLowerCase()
    .replace(/^\s*[\[【(][^\]】)]{1,18}[\]】)]\s*/u, "")
    .replace(/\s*[-–—]\s*[^-–—]{2,24}$/u, "")
    .replace(/[^가-힣a-z0-9]/g, "")
    .slice(0, 180);
}

export function canonicalArticleUrl(value) {
  const safe = safeUrl(value);
  if (!safe) return "";
  try {
    const url = new URL(safe);
    if (url.hostname.includes("news.google.com")) return "";
    url.hash = "";
    ["utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "ref", "source"].forEach(key => url.searchParams.delete(key));
    return `${url.hostname.replace(/^www\./, "")}${url.pathname.replace(/\/$/, "")}${url.search}`.toLowerCase();
  } catch { return ""; }
}

export function isYonhapArticle(article) {
  if ((article.source || "").trim() === "연합뉴스" || (article.provider || "").trim() === "연합뉴스") return true;
  try {
    const hostname = new URL(article.url || "").hostname.toLowerCase();
    return hostname === "yna.co.kr" || hostname.endsWith(".yna.co.kr");
  }
  catch { return false; }
}

export function getRelevance(article) {
  const assessment = article.assessment;
  const savedReasons = assessment?.autoReasons;
  if (assessment && Number.isFinite(assessment.autoRelevanceScore) && Number.isFinite(savedReasons?.relevanceRank)) {
    return {
      rank: savedReasons.relevanceRank,
      score: assessment.autoRelevanceScore,
      label: savedReasons.relevanceLabel || "낮음",
      titleMatch: !!savedReasons.relevanceTitleMatch,
      matchCount: Number(savedReasons.relevanceMatchCount || 0),
      reasons: Array.isArray(savedReasons.relevanceReasons) ? savedReasons.relevanceReasons : ["서버 관련도 판정"]
    };
  }
  const normalize = value => cleanText(value || "").normalize("NFKC").toLowerCase().replace(/\s+/g, " ");
  const title = normalize(article.title);
  const fullText = `${title} ${normalize(article.description || article.bodyText)}`;
  const authority = /대통령실|대통령|국무총리|총리실|국무조정실|기후에너지환경부|국무회의|국정현안관계장관회의|경제관계장관회의|공공기관운영위원회|에너지위원회|전력정책심의회|국회|국정감사|국정조사|현안질의/u;
  const energyContext = /전기안전|전력|전력망|전력수급|전기설비|전기화재|감전|정전|에너지|ess|전기차 충전/u;
  const criteria = [
    { rank: 1, reason: "① 공사 직접 거론", match: text => /한국전기안전공사|전기안전공사|\bkesco\b/u.test(text) },
    { rank: 2, reason: "② 전기화재·감전 사고", match: text => /전기[\s·ㆍ-]*화재|누전[\s·ㆍ-]*화재|전기적 요인|감전[\s·ㆍ-]*(?:사고|사망)|배전반[\s·ㆍ-]*화재|변압기[\s·ㆍ-]*화재/u.test(text) },
    { rank: 3, reason: "③ 정전·전력공급 장애", match: text => /대규모[\s·ㆍ-]*정전|광역[\s·ㆍ-]*정전|일대[\s·ㆍ-]*정전|전력[\s·ㆍ-]*공급[\s·ㆍ-]*중단|전력망[\s·ㆍ-]*장애|계통[\s·ㆍ-]*장애|블랙아웃|변전소[\s·ㆍ-]*고장|송전선로[\s·ㆍ-]*고장|배전선로[\s·ㆍ-]*고장/u.test(text) },
    { rank: 4, reason: "④ 정부·국회+전기·에너지 문맥", match: text => {
      if (!authority.test(text)) return false;
      const context = text.replace(/대통령실|대통령|국무총리|총리실|국무조정실|기후에너지환경부|국무회의|국정현안관계장관회의|경제관계장관회의|공공기관운영위원회|에너지위원회|전력정책심의회|국회|국정감사|국정조사|현안질의/gu, " ");
      return energyContext.test(context);
    } },
    { rank: 5, reason: "⑤ 전기 관련 법령·기준·기본계획", match: text => /전기안전관리법|전기사업법|한국전기설비규정|\bkec\b|전기설비기술기준|전기안전관리 기본계획|전력수급기본계획/u.test(text) },
    { rank: 6, reason: "⑥ 공공기관 경영평가·운영정책", match: text => /공공기관 경영실적 평가|공공기관 경영평가|경영평가편람|경영평가 결과|경영실적 평가결과|공공기관운영위원회|예산운용지침|총인건비|직무급|성과급|안전관리등급|경영공시|\balio\b/u.test(text) },
    { rank: 7, reason: "⑦ 신산업 설비안전·전략동향", match: text => /ess|에너지저장장치|배터리|전기차 충전/u.test(text) && /화재|감전|폭발|사고|안전점검|결함|리콜/u.test(text) || /전력망|송전망|배전망|분산에너지|데이터센터|재생에너지|전력수요/u.test(text) && /전기안전|안전관리|전기설비|화재|정전|검사|규제|기본계획/u.test(text) }
  ];
  const matches = criteria.filter(criterion => criterion.match(fullText));
  if (!matches.length) return { rank: 99, score: 0, label: "낮음", titleMatch: false, matchCount: 0, reasons: ["지정 관련도 기준 미일치"] };
  const primary = matches[0];
  const titleMatch = primary.match(title);
  const baseScore = { 1: 100, 2: 88, 3: 80, 4: 65, 5: 55, 6: 45, 7: 40 }[primary.rank];
  const score = primary.rank === 1 ? 100 : Math.min(99, baseScore + (titleMatch ? 7 : 0) + Math.min(5, (matches.length - 1) * 2));
  const label = primary.rank === 1 ? "매우 높음" : primary.rank <= 3 ? "높음" : primary.rank <= 5 ? "보통" : "관심";
  return { rank: primary.rank, score, label, titleMatch, matchCount: matches.length, reasons: matches.map(match => match.reason) };
}

export function relevanceSort(a, b) {
  const left = getRelevance(a);
  const right = getRelevance(b);
  const riskOrder = { critical: 3, watch: 2, routine: 1 };
  return left.rank - right.rank
    || Number(isYonhapArticle(b)) - Number(isYonhapArticle(a))
    || Number(b.starred) - Number(a.starred)
    || Number(right.titleMatch) - Number(left.titleMatch)
    || right.matchCount - left.matchCount
    || right.score - left.score
    || (riskOrder[b.risk] || 0) - (riskOrder[a.risk] || 0)
    || dateValue(b.pubDate) - dateValue(a.pubDate)
    || (a.title || "").localeCompare(b.title || "", "ko")
    || String(a.id || "").localeCompare(String(b.id || ""));
}

export function prioritySort(a, b) {
  const score = x => (x.starred ? 1000 : 0) + (x.risk === "critical" ? 300 : x.risk === "watch" ? 150 : 0) + Math.min((x.riskScore || 0) * 8, 80) + (x.sentiment === "positive" ? 8 : 0) + dateValue(x.pubDate) / 1e13;
  return score(b) - score(a);
}
