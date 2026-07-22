import {
  state, setState, settings, filters, setFilters, els,
  aiAbortController, setAiAbortController, nextAiRequestSerial, setAnalyzingSummary,
  saveDailyState, flushDailyState, loadDailyState
} from "../state/store.js";
import { getRelevance, relevanceSort } from "./collection.js";
import * as api from "../api/client.js";
import { friendlyError, safeUrl } from "../utils/strings.js";
import { downloadBlob } from "../utils/dom.js";
import { formatDateTime, localDateKey } from "../utils/dates.js";
import { showToast, setStatus } from "../ui/notifications.js?v=20260716-1";
import { renderAll } from "../ui/renderers.js";
import { setRuleSummary, refreshRuleSummaryIfNeeded } from "./ai-analysis.js";
import { flushArticleChanges } from "./articles.js?v=20260721-3";

const PREVIEW_PRESENTATION_PREFIX = "kesco-preview-presentation";

function restoreFinalPresentation(date, revision, snapshot) {
  const articles = snapshot?.articles || [];
  const articleSummaries = articles
    .filter(article => article.reportSummary)
    .map(article => ({ articleId: String(article.id), summary: article.reportSummary }));
  const presentation = {
    articleOrder: articles.map(article => String(article.id)),
    articleSummaries,
    articleSummarySourceRevision: articleSummaries.length ? revision : null,
  };
  try {
    localStorage.setItem(
      `${PREVIEW_PRESENTATION_PREFIX}:${date}:${revision}`,
      JSON.stringify(presentation),
    );
    return true;
  } catch {
    return false;
  }
}

/** 실제 검색 전 화면 시연용 샘플이다. 운영 데이터(articles/briefings)와 분리된 순수 프런트엔드 픽스처이며 서버에 저장되지 않는다. */
export function loadSample() {
  const base = new Date();
  const samples = [
    { title: "전기안전 취약시설 합동점검 확대…선제적 화재 예방", source: "샘플경제", description: "전통시장과 사회복지시설을 대상으로 계절별 안전점검과 예방 활동을 확대한다는 내용입니다.", category: "kesco_achievement", hours: 2, risk: "watch", sentiment: "neutral" },
    { title: "지역 에너지 복지 향상 위한 기관 간 업무협약", source: "샘플일보", description: "지역사회 안전망 강화와 취약계층 지원을 위한 협력 체계를 구축했습니다.", category: "kesco_achievement", hours: 5, risk: "routine", sentiment: "positive" },
    { title: "전기설비 안전관리 기준 개선 논의…현장 의견 수렴", source: "샘플뉴스", description: "제도 개선 과정에서 산업계와 현장의 의견을 반영하는 간담회가 열렸습니다.", category: "law_standard_plan", hours: 9, risk: "routine", sentiment: "neutral" },
    { title: "배터리 설비 화재 사고 이후 안전점검 실효성 논란", source: "샘플방송", description: "사고 예방 점검 체계와 후속 대응을 두고 개선 필요성이 제기됐습니다.", category: "new_industry_safety", hours: 12, risk: "critical", sentiment: "negative" }
  ];
  state.articles = samples.map((s, i) => ({
    id: `sample-${i}`, title: s.title, source: s.source, description: s.description, category: s.category,
    pubDate: new Date(base.getTime() - s.hours * 3600000).toISOString(), url: "", isDemo: true, manual: false,
    included: true, starred: false, topIssue: false, note: "", risk: s.risk, riskScore: 0, sentiment: s.sentiment, matchedKeywords: []
  }));
  state.demo = true;
  state.provider = "샘플 데이터";
  state.fetchedAt = new Date().toISOString();
  setRuleSummary(true);
  renderAll();
  setStatus("idle", "샘플 화면 · 실제 검색 전");
}

export async function importFile(e) {
  const file = e.target.files?.[0]; e.target.value = ""; if (!file) return;
  try {
    const text = await file.text();
    let articlesImported = 0;
    if (file.name.toLowerCase().endsWith(".json")) {
      const data = JSON.parse(text);
      const result = await api.importJsonExport(state.date, data, "replace");
      articlesImported = result.data.articlesImported;
    } else {
      const result = await api.importCsvExport(state.date, text);
      articlesImported = result.data.articlesImported;
    }
    setState(await loadDailyState(state.date));
    state.demo = false;
    refreshRuleSummaryIfNeeded();
    renderAll();
    showToast(`${articlesImported}건을 브리핑에 반영했습니다.`, "success");
  } catch (error) { showToast(`가져오기 실패: ${friendlyError(error)}`, "error"); }
}

export async function exportJson() {
  try {
    const result = await api.getJsonExport(state.date);
    downloadBlob(JSON.stringify(result.data, null, 2), `KESCO_언론브리핑_${state.date}.json`, "application/json;charset=utf-8");
    showToast("당일 브리핑 JSON을 저장했습니다.", "success");
  } catch (error) { showToast(`내보내기 실패: ${friendlyError(error)}`, "error"); }
}

export async function exportCsv() {
  try {
    const csvText = await api.getCsvExportText(state.date);
    downloadBlob(csvText, `KESCO_언론기사_${state.date}.csv`, "text/csv;charset=utf-8");
    showToast("기사 목록 CSV를 저장했습니다. (일부 필드만 포함하는 손실형 교환 포맷입니다)", "success");
  } catch (error) { showToast(`내보내기 실패: ${friendlyError(error)}`, "error"); }
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

export async function openPreview() {
  const previewWindow = window.open("about:blank", "_blank");
  if (previewWindow) previewWindow.opener = null;
  try {
    await flushArticleChanges();
    await flushDailyState();
    const previewUrl = `/preview/${encodeURIComponent(state.date)}`;
    if (previewWindow) previewWindow.location.replace(previewUrl);
    else showToast("팝업이 차단되어 CEO 미리보기를 열지 못했습니다.", "error");
  } catch (error) {
    previewWindow?.close();
    showToast(`CEO 미리보기 준비 실패: ${friendlyError(error)}`, "error");
  }
}

export async function openFinalReport() {
  const reportWindow = window.open("about:blank", "_blank");
  if (!reportWindow) {
    showToast("팝업이 차단되어 최종본을 열지 못했습니다.", "error");
    return;
  }
  reportWindow.opener = null;
  try {
    const result = await api.listBriefingVersions(state.date);
    const versions = result.data?.versions || [];
    const latest = versions.reduce(
      (current, item) => !current || item.version > current.version ? item : current,
      null,
    );
    if (!latest) throw new Error(`${state.date} 최종 확정본이 없습니다.`);
    const reportUrl = `/report/${encodeURIComponent(state.date)}?version=${encodeURIComponent(latest.version)}`;
    reportWindow.location.replace(reportUrl);
  } catch (error) {
    reportWindow.close();
    showToast(`최종본 보기 실패: ${friendlyError(error)}`, "error");
  }
}

export async function cancelFinalization() {
  if (!window.confirm(`최종 확정 v${state.latestFinalVersion}을 취소하고 직전 작업본으로 돌아가시겠습니까? 확정 기록은 보존됩니다.`)) return;
  try {
    const version = await api.getBriefingVersion(state.date, state.latestFinalVersion);
    await api.reopenBriefing(state.date, state.revision);
    setState(await loadDailyState(state.date));
    const presentationRestored = restoreFinalPresentation(
      state.date,
      state.revision,
      version.data?.snapshot,
    );
    renderAll();
    showToast(
      presentationRestored
        ? "최종 확정을 취소하고 직전 CEO 미리보기 작업본으로 돌아왔습니다."
        : "최종 확정은 취소했지만 미리보기 임시 상태는 복원하지 못했습니다.",
      presentationRestored ? "success" : "error",
    );
    setStatus("idle", `확정 취소 · 최종 기록 v${state.latestFinalVersion} 보존`);
  } catch (error) {
    showToast(`확정 취소 실패: ${friendlyError(error)}`, "error");
  }
}

export async function resetTodayWork() {
  if (state.date !== localDateKey()) {
    showToast("오늘 날짜의 작업만 초기화할 수 있습니다.", "error");
    return;
  }
  if (state.status === "final") {
    showToast("최종 확정된 작업본은 초기화할 수 없습니다.", "error");
    return;
  }
  const confirmed = window.confirm(
    "오늘 수집한 기사, 선정·메모·Top Issues, 그룹, AI 분석과 추천, 요약을 모두 삭제합니다. 초기화 전 DB 백업은 자동 생성됩니다. 처음부터 다시 시작하시겠습니까?"
  );
  if (!confirmed) return;
  const button = document.getElementById("resetTodayBtn");
  button.disabled = true;
  try {
    await flushArticleChanges();
    await flushDailyState();
    const result = await api.resetTodayWork(state.date, state.revision);
    setState(await loadDailyState(state.date));
    setFilters({ text: "", category: "all", risk: "all", selection: "all", sort: "review" });
    els.articleSearch.value = "";
    els.categoryFilter.value = "all";
    els.riskFilter.value = "all";
    els.selectionFilter.value = "all";
    els.sortOrder.value = "review";
    renderAll();
    setStatus("idle", "오늘 작업 초기화 완료 · 기사 수집부터 다시 시작하세요");
    showToast(`오늘 작업을 초기화했습니다. 안전 백업: ${result.data.backupFile}`, "success");
  } catch (error) {
    if (error.code === "BRIEFING_REVISION_CONFLICT") {
      setState(await loadDailyState(state.date));
      renderAll();
    }
    showToast(`오늘 작업 초기화 실패: ${friendlyError(error)}`, "error");
  } finally {
    button.disabled = false;
  }
}

export async function changeReportDate() {
  const next = els.reportDate.value; if (!next) return;
  aiAbortController?.abort();
  setAiAbortController(null);
  nextAiRequestSerial();
  setAnalyzingSummary(false);
  saveDailyState();
  try {
    setState(await loadDailyState(next));
  } catch (error) {
    showToast(`날짜 전환 실패: ${friendlyError(error)}`, "error");
    return;
  }
  setFilters({ text: "", category: "all", risk: "all", selection: "all", sort: "relevance" });
  els.articleSearch.value = ""; els.categoryFilter.value = "all"; els.riskFilter.value = "all"; els.selectionFilter.value = "all"; els.sortOrder.value = "review"; renderAll();
  setStatus(state.articles.length ? "live" : "idle", state.articles.length ? `${next} 저장본 ${state.articles.length}건` : `${next} 저장본이 없습니다`);
}
