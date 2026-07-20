import {
  state, settings, els, AI_API_BASE,
  isAnalyzingSummary, setAnalyzingSummary, aiRequestSerial, nextAiRequestSerial,
  aiAbortController, setAiAbortController, aiServerState, setAiServerState
} from "../state/store.js";
import { autoResize } from "../utils/dom.js";
import { countBy, friendlyError, escapeHtml, escapeAttr } from "../utils/strings.js";
import { formatDateTime } from "../utils/dates.js";
import { primaryIssueByArticle } from "../utils/issues.js";
import { fetchWithTimeout } from "../utils/net.js";
import { prioritySort, relevanceSort } from "./collection.js";
import { renderAll } from "../ui/renderers.js";
import { showToast } from "../ui/notifications.js?v=20260716-1";
import * as api from "../api/client.js";

export function renderSummary() {
  if (state.status !== "final" && !state.summary && state.articles.length) refreshRuleSummaryIfNeeded();
  if (els.summaryEditor.value !== (state.summary || "")) els.summaryEditor.value = state.summary || "";
  if (els.actionNote.value !== (state.actionNote || "")) els.actionNote.value = state.actionNote || "";
  els.printSummary.textContent = state.summary || "수집 기사 없음";
  els.printActionNote.textContent = state.actionNote || "별도 지시사항 없음";
  autoResize(els.summaryEditor);
  renderAiSummaryStatus();
}

export function generateSummary() {
  const items = state.articles.filter(a => a.included);
  if (!items.length) return "• 현재 CEO 보고 대상으로 선택된 기사가 없습니다.\n• 기사를 검색하거나 직접 추가한 뒤 포함 여부를 확인해 주세요.";
  const positive = items.filter(a => a.sentiment === "positive");
  const sources = new Set(items.map(a => a.source).filter(Boolean)).size;
  const issueByArticle = primaryIssueByArticle(state.issues);
  const top = [...items].sort((a, b) => (issueByArticle.get(a.id)?.autoReviewRank || 999999) - (issueByArticle.get(b.id)?.autoReviewRank || 999999) || prioritySort(a, b))[0];
  const topIssue = issueByArticle.get(top.id);
  const priorityIssueCount = state.issues.filter(issue => (issue.effectiveReviewStars || 0) >= 4).length;
  const categories = countBy(items, "category");
  const topCategory = Object.entries(categories).sort((a,b) => b[1]-a[1])[0];
  const categoryLabel = settings.queries.find(q => q.id === topCategory?.[0])?.label || "주요 이슈";
  const lines = [
    `• 최근 ${settings.lookback}시간 기준 ${sources}개 매체의 관련 보도 ${items.length}건을 CEO 보고 대상으로 선별했습니다.`,
    `• 최우선 검토 군집은 「${topIssue?.effectiveTitle || top.title}」이며, 검토별점 ${topIssue?.effectiveReviewStars || 1}점·자동순위 ${topIssue?.autoReviewRank || "미산정"}위입니다.`,
    `• 보도 비중은 ${categoryLabel} 분야가 ${topCategory?.[1] || 0}건으로 가장 높고, 우선 검토 군집 ${priorityIssueCount}개·긍정 보도 ${positive.length}건입니다.`
  ];
  if ((topIssue?.effectiveReviewStars || 0) >= 4) lines.push("• 제언: 상위 검토 군집의 긴급성과 대응적합도 근거를 확인하고, 필요 시 주관 부서의 사실관계와 대응 메시지를 정렬할 필요가 있습니다.");
  else lines.push("• 제언: 상위 검토 군집은 많지 않으며, 주요 성과 보도의 후속 확산 기회를 함께 검토할 수 있습니다.");
  return lines.join("\n");
}

export function setRuleSummary(force = false) {
  if (!force && state.summary && state.summaryMode !== "rule") return;
  state.summary = generateSummary();
  state.summaryEdited = false;
  state.summaryMode = "rule";
  state.summaryModel = "";
  state.summaryGeneratedAt = "";
  state.summaryInputSignature = "";
  state.summaryContextLength = 0;
  state.summarySelectedCount = state.articles.filter(article => article.included).length;
  state.summaryEvidenceIds = [];
  state.summaryEvidenceMap = [];
  state.summaryCoverage = null;
  state.summaryError = "";
  state.aiStale = false;
  state.aiAnalysis = null;
  state.aiValidationWarnings = [];
}

export function refreshRuleSummaryIfNeeded() {
  if (state.summaryMode === "rule") setRuleSummary(true);
}

export async function checkAiServer() {
  setAiServerState({ ...aiServerState, checking: true, error: "" });
  renderAiSummaryStatus();
  try {
    const response = await fetchWithTimeout(`${AI_API_BASE}/health`, { headers: { Accept: "application/json" } }, 7000);
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || `AI 도우미 응답 ${response.status}`);
    const models = data.models || [];
    setAiServerState({ checking: false, online: models.length > 0 && !data.error, models, defaultModel: data.defaultModel || "", error: data.error || "" });
    populateAiModelOptions();
  } catch (error) {
    setAiServerState({ checking: false, online: false, models: [], defaultModel: "", error: friendlyError(error) });
  }
  renderAiSummaryStatus();
}

export function populateAiModelOptions() {
  const names = aiServerState.models.map(model => model.name).filter(Boolean);
  const fallbackNames = ["gemma4:31b", "gemma4:26b", "gemma4:e4b", "gemma4:e2b"];
  const options = names.length ? names : fallbackNames;
  if (!options.includes(settings.aiModel)) settings.aiModel = aiServerState.defaultModel || options[0];
  els.aiModelSelect.innerHTML = options.map(name => `<option value="${escapeAttr(name)}">${escapeHtml(name)}</option>`).join("");
  els.aiModelSelect.value = settings.aiModel;
}

export function renderAiSummaryStatus() {
  if (!els.aiSummaryStatus) return;
  const selected = state.articles.filter(article => article.included);
  const modelChanged = !!state.summaryModel && state.summaryModel !== settings.aiModel;
  const stale = ["ai", "ai-edited"].includes(state.summaryMode) && (state.aiStale || modelChanged);
  const coverage = state.summaryCoverage;
  const serverRunning = state.aiRunStatus === "running";
  const cancelling = state.aiRunStatus === "cancelling";
  const analyzing = isAnalyzingSummary || serverRunning || cancelling;

  els.aiModelSelect.value = [...els.aiModelSelect.options].some(option => option.value === settings.aiModel) ? settings.aiModel : els.aiModelSelect.value;
  els.aiModelSelect.disabled = state.status === "final" || analyzing || !aiServerState.online;
  if (coverage && ["ai", "ai-edited"].includes(state.summaryMode)) {
    const analyzed = coverage.selected ?? state.summarySelectedCount ?? 0;
    const rssCount = coverage.rssOnlyCount ?? coverage.summaryCount ?? 0;
    const extra = [
      coverage.metaOnlyCount ? `메타 ${coverage.metaOnlyCount}건` : "",
      coverage.noteOnlyCount ? `메모 ${coverage.noteOnlyCount}건` : "",
      coverage.titleOnlyCount ? `제목 ${coverage.titleOnlyCount}건` : "",
      coverage.failedCount ? `실패 ${coverage.failedCount}건` : ""
    ].filter(Boolean).join(" · ");
    els.aiCoverageState.textContent = `분석 ${analyzed}/선정 ${selected.length}건 · 본문 ${coverage.bodyCount || 0}건 · RSS ${rssCount}건${extra ? ` · ${extra}` : ""}`;
  } else {
    els.aiCoverageState.textContent = `선정 ${selected.length}건`;
  }

  els.aiConnectionState.classList.remove("online", "offline");
  if (aiServerState.checking) {
    els.aiConnectionState.textContent = "AI 도우미 확인 중";
  } else if (aiServerState.online) {
    els.aiConnectionState.classList.add("online");
    els.aiConnectionState.textContent = "Ollama 로컬 연결";
  } else {
    els.aiConnectionState.classList.add("offline");
    els.aiConnectionState.textContent = "AI 도우미 오프라인";
  }

  els.aiSummaryStatus.className = "ai-summary-status no-print";
  if (cancelling) {
    els.aiSummaryStatus.classList.add("busy");
    els.aiSummaryStatus.textContent = `${settings.aiModel} 분석 취소를 요청했습니다. Ollama 작업을 정리하는 중입니다.`;
  } else if (analyzing) {
    els.aiSummaryStatus.classList.add("busy");
    const safeMode = settings.aiModel.toLowerCase().includes(":31b") ? " · 31B 심층 분석(context 64K·최대 20분)" : " · 최대 20분";
    els.aiSummaryStatus.textContent = `${settings.aiModel}이 선정 기사 ${Math.min(selected.length, 20)}건의 본문을 수집하고 경영메시지를 분석 중입니다${safeMode}. 이 버튼으로 즉시 취소할 수 있으며 창을 닫으면 실행도 자동 중단됩니다.`;
  } else if (state.summaryError) {
    els.aiSummaryStatus.classList.add("error");
    els.aiSummaryStatus.textContent = state.summaryError;
  } else if (stale) {
    els.aiSummaryStatus.classList.add("stale");
    els.aiSummaryStatus.textContent = "선정 기사·메모 또는 분석 모델이 변경되었습니다. 기존 메시지는 유지되며, 최신 근거로 다시 생성하는 것이 좋습니다.";
  } else if (["ai", "ai-edited"].includes(state.summaryMode) && state.summaryGeneratedAt) {
    els.aiSummaryStatus.classList.add("ready");
    const edited = state.summaryMode === "ai-edited" ? " · 담당자 수정본" : "";
    const confidence = state.aiAnalysis?.confidence ? ` · 신뢰도 ${state.aiAnalysis.confidence}` : "";
    const warningLabels = {
      UNSUPPORTED_NUMBER: "숫자·날짜",
      KESCO_ROLE_CONFUSION: "역할 혼동",
      INVESTIGATION_OVERSTATED: "조사 중 표현",
      UNATTRIBUTED_CLAIM: "주장 귀속",
      REFERENCE_SCOPE_INVALID: "참고 범위"
    };
    const warningKinds = [...new Set((state.aiValidationWarnings || []).map(item => warningLabels[item.code] || item.code))];
    const warnings = warningKinds.length ? ` · 자동검증 경고 ${state.aiValidationWarnings.length}건(${warningKinds.join(", ")})` : " · 자동검증 통과";
    const contextLength = state.summaryContextLength ? ` · context ${Math.round(state.summaryContextLength / 1024)}K` : "";
    els.aiSummaryStatus.textContent = `${formatDateTime(state.summaryGeneratedAt)} 생성 · ${state.summaryModel}${contextLength} · 선정 ${state.summarySelectedCount}건${confidence}${warnings}${edited}`;
  } else if (!selected.length) {
    els.aiSummaryStatus.textContent = "먼저 브리핑에 사용할 기사를 선택해 주세요.";
  } else if (!aiServerState.online) {
    els.aiSummaryStatus.textContent = "start_kesco_briefing.command를 실행해 이 화면을 다시 열면 로컬 Gemma 4 분석을 사용할 수 있습니다.";
  } else {
    els.aiSummaryStatus.textContent = `선정 기사 ${selected.length}건이 준비됐습니다. Gemma 4 경영메시지 생성을 실행하세요.`;
  }

  els.generateAiSummaryBtn.disabled = state.status === "final" || cancelling || (!analyzing && (!selected.length || !aiServerState.online));
  els.ruleSummaryBtn.disabled = state.status === "final" || analyzing;
  els.generateAiSummaryBtn.classList.toggle("ai-cancel-btn", analyzing);
  els.generateAiSummaryBtn.innerHTML = cancelling
    ? '<span class="spinner"></span><span>취소 처리 중</span>'
    : analyzing
      ? "AI 분석 취소"
      : "Gemma 4 경영메시지 생성";
  els.generateAiSummaryBtn.title = analyzing ? "실행 중인 Ollama 분석을 중단합니다." : (!selected.length ? "브리핑 기사를 먼저 선택해 주세요." : "선정 기사 본문과 RSS 요약을 분석합니다.");
}

export function handleAiAnalysisAction() {
  if (isAnalyzingSummary || ["running", "cancelling"].includes(state.aiRunStatus)) return cancelAiManagementSummary();
  return generateAiManagementSummary();
}

async function refreshAiRunState() {
  const briefing = (await api.getBriefing(state.date)).data;
  const latestRun = briefing.aiState?.latestRun;
  state.aiRunId = latestRun?.id || "";
  state.aiRunStatus = latestRun?.status || "idle";
  state.summaryError = briefing.aiState?.currentError ? `최근 AI 실행 실패: ${briefing.aiState.currentError} · 마지막 정상 결과는 유지됩니다.` : "";
  return state.aiRunStatus;
}

export async function cancelAiManagementSummary() {
  if (state.aiRunStatus === "cancelling") return;
  nextAiRequestSerial();
  state.aiRunStatus = "cancelling";
  renderAiSummaryStatus();
  try {
    await api.cancelBriefingAnalysis(state.date);
    aiAbortController?.abort();
    setAiAbortController(null);
    setAnalyzingSummary(false);
    for (let attempt = 0; attempt < 20; attempt += 1) {
      const status = await refreshAiRunState();
      if (status !== "running") break;
      await new Promise(resolve => window.setTimeout(resolve, 250));
    }
    if (state.aiRunStatus === "running") state.aiRunStatus = "cancelling";
    else showToast("AI 분석을 취소하고 모델 메모리를 정리했습니다.", "success");
  } catch (error) {
    state.summaryError = friendlyError(error);
    showToast(`AI 분석 취소 실패: ${state.summaryError}`, "error");
    await refreshAiRunState().catch(() => {});
  } finally {
    renderAll();
  }
}

export async function generateAiManagementSummary() {
  const selectedAll = state.articles.filter(article => article.included).sort(relevanceSort);
  if (!selectedAll.length) { showToast("브리핑에 사용할 기사를 먼저 선택해 주세요.", "error"); return; }
  if (!aiServerState.online) { state.summaryError = "AI 도우미가 연결되지 않았습니다. Ollama 상태를 확인해 주세요."; renderSummary(); return; }

  const selected = selectedAll.slice(0, 20);
  const requestId = nextAiRequestSerial();
  aiAbortController?.abort();
  setAiAbortController(new AbortController());
  const requestDate = state.date;
  const originalSummary = state.summary;
  state.summaryError = "";
  state.aiRunId = "";
  state.aiRunStatus = "running";
  setAnalyzingSummary(true);
  renderSummary();
  if (selectedAll.length > 20) showToast("관련도순 상위 20건을 AI 분석에 사용합니다.");

  try {
    const response = await api.analyzeBriefing(state.date, state.revision, settings.aiModel, aiAbortController.signal);
    const data = response.data;
    if (requestId !== aiRequestSerial) return;
    if (state.date !== requestDate || state.summary !== originalSummary) {
      throw new Error("분석 중 선정 기사·메모 또는 메시지가 변경되어 결과를 적용하지 않았습니다. 다시 실행해 주세요.");
    }

    const run = data.run;
    state.aiAnalysis = run.response?.analysis || null;
    state.aiValidationWarnings = run.response?.validationWarnings || [];
    state.summaryEvidenceMap = Array.isArray(run.request?.articles) ? run.request.articles.map(article => ({
      id: article.id,
      title: article.title,
      source: article.source,
      basis: article.bodyStatus,
      error: article.bodyError || ""
    })) : [];
    state.summary = data.situationSummary;
    state.summaryEdited = data.summaryMode === "ai-edited";
    state.summaryMode = data.summaryMode;
    state.summaryModel = run.model || settings.aiModel;
    state.summaryGeneratedAt = run.finishedAt || new Date().toISOString();
    state.summaryInputSignature = run.inputSignature;
    state.summaryContextLength = run.request?.contextLength || 0;
    state.summarySelectedCount = selected.length;
    state.summaryEvidenceIds = Object.keys(run.evidence || {});
    state.summaryCoverage = {
      selected: selected.length,
      bodyCount: state.summaryEvidenceMap.filter(article => article.basis === "full_text").length,
      rssOnlyCount: state.summaryEvidenceMap.filter(article => article.basis === "summary_only").length,
      titleOnlyCount: state.summaryEvidenceMap.filter(article => article.basis === "missing" && !article.error).length,
      failedCount: state.summaryEvidenceMap.filter(article => article.error).length
    };
    state.summaryError = "";
    state.aiStale = false;
    state.aiRunId = run.id || "";
    state.aiRunStatus = "success";
    state.revision = data.briefingRevision;
    showToast(`Gemma 4가 선정 기사 ${selected.length}건을 분석했습니다.`, "success");
  } catch (error) {
    if (requestId !== aiRequestSerial) return;
    state.aiRunStatus = error.code === "AI_ALREADY_RUNNING" ? "running" : "failed";
    state.summaryError = friendlyError(error);
    showToast(`AI 분석 실패: ${state.summaryError}`, "error");
  } finally {
    if (requestId === aiRequestSerial) {
      setAnalyzingSummary(false);
      setAiAbortController(null);
    }
    renderAll();
  }
}

export function formatAiAnalysis(analysis, evidenceMap = []) {
  const references = (analysis.keyIssues || [])
    .filter(issue => issue.urgency === "reference")
    .map(issue => [issue.summary, issue.managementImpact].filter(Boolean).join(" ").trim())
    .filter(Boolean);
  const lines = [
    "① 오늘의 핵심",
    analysis.managementMessage?.text?.trim() || "핵심 경영메시지를 생성하지 못했습니다.",
    "",
    "② 경영 시사점",
    analysis.situationSummary?.text?.trim() || "경영 시사점을 생성하지 못했습니다.",
    "",
    "③ 참고 동향",
    references.length ? references.join("\n\n") : "별도 참고 동향 없음."
  ];
  return lines.join("\n");
}
