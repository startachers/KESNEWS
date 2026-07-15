import {
  state, setState, settings, filters, setFilters, els, RISK_LABELS, SENTIMENT_LABELS,
  aiAbortController, setAiAbortController, nextAiRequestSerial, setAnalyzingSummary,
  saveDailyState, loadDailyState
} from "../state/store.js";
import { classifyArticle, deduplicate, getRelevance, relevanceSort } from "./collection.js";
import { parseCsv } from "../utils/csv.js";
import { csvCell, friendlyError, safeUrl, uid } from "../utils/strings.js";
import { downloadBlob } from "../utils/dom.js";
import { parseDate, formatDateTime } from "../utils/dates.js";
import { showToast, setStatus } from "../ui/notifications.js";
import { renderAll } from "../ui/renderers.js";
import { setRuleSummary, refreshRuleSummaryIfNeeded } from "./ai-analysis.js";
import { persistAndRender } from "./articles.js";

export function loadSample() {
  const base = new Date();
  const samples = [
    { title: "전기안전 취약시설 합동점검 확대…선제적 화재 예방", source: "샘플경제", description: "전통시장과 사회복지시설을 대상으로 계절별 안전점검과 예방 활동을 확대한다는 내용입니다.", category: "safety", hours: 2 },
    { title: "지역 에너지 복지 향상 위한 기관 간 업무협약", source: "샘플일보", description: "지역사회 안전망 강화와 취약계층 지원을 위한 협력 체계를 구축했습니다.", category: "community", hours: 5 },
    { title: "전기설비 안전관리 기준 개선 논의…현장 의견 수렴", source: "샘플뉴스", description: "제도 개선 과정에서 산업계와 현장의 의견을 반영하는 간담회가 열렸습니다.", category: "policy", hours: 9 },
    { title: "배터리 설비 화재 사고 이후 안전점검 실효성 논란", source: "샘플방송", description: "사고 예방 점검 체계와 후속 대응을 두고 개선 필요성이 제기됐습니다.", category: "industry", hours: 12 }
  ];
  state.articles = samples.map((s, i) => classifyArticle({ id: `sample-${i}`, ...s, pubDate: new Date(base.getTime()-s.hours*3600000).toISOString(), url: "", isDemo: true, included: true }));
  state.demo = true;
  state.provider = "샘플 데이터";
  state.fetchedAt = new Date().toISOString();
  setRuleSummary(true);
  persistAndRender();
  setStatus("idle", "샘플 화면 · 실제 검색 전");
}

export async function importFile(e) {
  const file = e.target.files?.[0]; e.target.value = ""; if (!file) return;
  try {
    const text = await file.text();
    if (file.name.toLowerCase().endsWith(".json")) {
      const data = JSON.parse(text);
      const imported = Array.isArray(data) ? data : (data.articles || []);
      if (!Array.isArray(imported)) throw new Error("기사 배열을 찾을 수 없습니다.");
      state.articles = deduplicate([...state.articles.filter(a => !a.isDemo), ...imported.map(normalizeImportedArticle)]);
      if (data.preparedBy) state.preparedBy = data.preparedBy;
      if (data.summary) {
        state.summary = data.summary;
        state.summaryEdited = true;
        state.summaryMode = "manual";
        state.summaryModel = "";
        state.summaryGeneratedAt = "";
        state.summaryInputSignature = "";
        state.summaryEvidenceIds = [];
        state.summaryEvidenceMap = [];
        state.summaryCoverage = null;
        state.summaryError = "";
        state.aiAnalysis = null;
        if (["ai", "ai-edited"].includes(data.summaryMode) && data.aiAnalysis) {
          state.summaryMode = data.summaryMode;
          state.summaryEdited = data.summaryMode === "ai-edited";
          state.summaryModel = data.summaryModel || "";
          state.summaryGeneratedAt = data.summaryGeneratedAt || "";
          state.summaryInputSignature = data.summaryInputSignature || "";
          state.summarySelectedCount = Number(data.summarySelectedCount || 0);
          state.summaryEvidenceIds = Array.isArray(data.summaryEvidenceIds) ? data.summaryEvidenceIds : [];
          state.summaryEvidenceMap = Array.isArray(data.summaryEvidenceMap) ? data.summaryEvidenceMap : [];
          state.summaryCoverage = data.summaryCoverage || null;
          state.aiAnalysis = data.aiAnalysis;
        }
      }
    } else {
      const rows = parseCsv(text);
      state.articles = deduplicate([...state.articles.filter(a => !a.isDemo), ...rows.map(normalizeImportedArticle)]);
    }
    state.demo = false;
    refreshRuleSummaryIfNeeded();
    persistAndRender(); showToast(`${state.articles.length}건을 브리핑에 반영했습니다.`, "success");
  } catch (error) { showToast(`가져오기 실패: ${friendlyError(error)}`, "error"); }
}

export function normalizeImportedArticle(item) {
  const raw = {
    id: item.id || uid(), title: item.title || item.제목 || "제목 없음", source: item.source || item.매체 || "출처 미상",
    url: item.url || item.링크 || "", pubDate: parseDate(item.pubDate || item.date || item.보도일시), description: item.description || item.summary || item.요약 || "",
    category: item.category || item.분류 || "direct", manual: true, note: item.note || item.메모 || ""
  };
  const article = classifyArticle(raw);
  if (item.risk && RISK_LABELS[item.risk]) article.risk = item.risk;
  const selectedValue = item.included ?? item.브리핑선정 ?? item.포함;
  const starredValue = item.starred ?? item.중요;
  article.included = selectedValue === undefined ? true : ![false, "N", "n", "false", "0"].includes(selectedValue);
  article.starred = [true, "Y", "y", "true", "1"].includes(starredValue);
  return article;
}

export function exportJson() {
  const payload = { version: 1, exportedAt: new Date().toISOString(), organization: "한국전기안전공사", ...state };
  downloadBlob(JSON.stringify(payload, null, 2), `KESCO_언론브리핑_${state.date}.json`, "application/json;charset=utf-8");
  showToast("당일 브리핑 JSON을 저장했습니다.", "success");
}

export function exportCsv() {
  const headers = ["브리핑선정","중요","위험도","정서","분류","관련도","관련도점수","관련도근거","제목","매체","보도일시","URL","키워드","메모"];
  const rows = state.articles.map(a => {
    const relevance = getRelevance(a);
    return [a.included ? "Y":"N", a.starred ? "Y":"N", RISK_LABELS[a.risk], SENTIMENT_LABELS[a.sentiment], settings.queries.find(q=>q.id===a.category)?.label || a.category, relevance.label, relevance.score, relevance.reasons.join("|"), a.title, a.source, a.pubDate, a.url, (a.matchedKeywords||[]).join("|"), a.note || ""];
  });
  const csv = "﻿" + [headers, ...rows].map(row => row.map(csvCell).join(",")).join("\r\n");
  downloadBlob(csv, `KESCO_언론기사_${state.date}.csv`, "text/csv;charset=utf-8");
  showToast("기사 목록 CSV를 저장했습니다.", "success");
}

export async function copySummary() {
  const selected = state.articles.filter(article => article.included).sort(relevanceSort);
  const articleList = selected.length ? selected.map((article, index) => {
    const relevance = getRelevance(article);
    const note = article.note ? `\n   메모: ${article.note}` : "";
    const link = safeUrl(article.url) ? `\n   원문: ${safeUrl(article.url)}` : "";
    return `${index + 1}. [${relevance.rank < 99 ? `관련 ${relevance.rank}순위` : "관련 기준 외"}] ${article.title}\n   ${article.source || "출처 미상"} · ${formatDateTime(article.pubDate)}${note}${link}`;
  }).join("\n\n") : "선정된 기사 없음";
  const text = `[한국전기안전공사 일일 언론브리핑 | ${state.date}]\n\n${state.summary || "수집 기사 없음"}\n\n[브리핑 선정 기사 ${selected.length}건]\n${articleList}\n\n[CEO 참고·지시사항]\n${state.actionNote || "별도 지시사항 없음"}`;
  try { await navigator.clipboard.writeText(text); showToast("브리핑 요약을 복사했습니다.", "success"); }
  catch {
    const area = document.createElement("textarea"); area.value = text; document.body.appendChild(area); area.select(); document.execCommand("copy"); area.remove(); showToast("브리핑 요약을 복사했습니다.", "success");
  }
}

export function changeReportDate() {
  const next = els.reportDate.value; if (!next) return;
  aiAbortController?.abort();
  setAiAbortController(null);
  nextAiRequestSerial();
  setAnalyzingSummary(false);
  saveDailyState(); setState(loadDailyState(next)); setFilters({ text: "", category: "all", risk: "all", selection: "all", sort: "relevance" });
  els.articleSearch.value = ""; els.categoryFilter.value = "all"; els.riskFilter.value = "all"; els.selectionFilter.value = "all"; els.sortOrder.value = "relevance"; renderAll();
  setStatus(state.articles.length ? "live" : "idle", state.articles.length ? `${next} 저장본 ${state.articles.length}건` : `${next} 저장본이 없습니다`);
}
