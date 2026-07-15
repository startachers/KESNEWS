import {
  state, settings, els, RISK_LABELS, AI_API_BASE, AI_SESSION_TOKEN,
  isAnalyzingSummary, setAnalyzingSummary, aiRequestSerial, nextAiRequestSerial,
  aiAbortController, setAiAbortController, aiServerState, setAiServerState, saveDailyState
} from "../state/store.js";
import { autoResize } from "../utils/dom.js";
import { countBy, friendlyError, escapeHtml, escapeAttr } from "../utils/strings.js";
import { formatDateTime } from "../utils/dates.js";
import { fetchWithTimeout } from "../utils/net.js";
import { prioritySort, relevanceSort, getRelevance, normalizedArticleTitle, canonicalArticleUrl } from "./collection.js";
import { renderAll } from "../ui/renderers.js";
import { showToast } from "../ui/notifications.js";

export function renderSummary() {
  if (!state.summary && state.articles.length) refreshRuleSummaryIfNeeded();
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
  const critical = items.filter(a => a.risk === "critical");
  const watch = items.filter(a => a.risk === "watch");
  const positive = items.filter(a => a.sentiment === "positive");
  const sources = new Set(items.map(a => a.source).filter(Boolean)).size;
  const top = [...items].sort(prioritySort)[0];
  const categories = countBy(items, "category");
  const topCategory = Object.entries(categories).sort((a,b) => b[1]-a[1])[0];
  const categoryLabel = settings.queries.find(q => q.id === topCategory?.[0])?.label || "주요 이슈";
  const lines = [
    `• 최근 ${settings.lookback}시간 기준 ${sources}개 매체의 관련 보도 ${items.length}건을 CEO 보고 대상으로 선별했습니다.`,
    `• 최우선 검토 보도는 「${top.title}」이며, ${RISK_LABELS[top.risk]} 단계로 분류했습니다.`,
    `• 보도 비중은 ${categoryLabel} 분야가 ${topCategory?.[1] || 0}건으로 가장 높고, 긴급 ${critical.length}건·주의 ${watch.length}건·긍정 ${positive.length}건입니다.`
  ];
  if (critical.length) lines.push("• 제언: 긴급 보도의 사실관계와 확산 추이를 우선 확인하고, 필요 시 주관 부서 메시지를 조기에 정렬할 필요가 있습니다.");
  else if (watch.length) lines.push("• 제언: 주의 보도의 추가 확산 여부를 모니터링하고 문의 대응용 핵심 사실을 사전 점검하는 것이 좋습니다.");
  else lines.push("• 제언: 즉시 대응이 필요한 위험 신호는 낮으며, 주요 성과 보도의 후속 확산 기회를 검토할 수 있습니다.");
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
  state.summarySelectedCount = state.articles.filter(article => article.included).length;
  state.summaryEvidenceIds = [];
  state.summaryEvidenceMap = [];
  state.summaryCoverage = null;
  state.summaryError = "";
  state.aiAnalysis = null;
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
    setAiServerState({ checking: false, online: true, models: data.models || [], defaultModel: data.defaultModel || "", error: "" });
    populateAiModelOptions();
  } catch (error) {
    setAiServerState({ checking: false, online: false, models: [], defaultModel: "", error: friendlyError(error) });
  }
  renderAiSummaryStatus();
}

export function populateAiModelOptions() {
  const names = aiServerState.models.map(model => model.name).filter(Boolean);
  const fallbackNames = ["gemma4:26b", "gemma4:e4b", "gemma4:e2b"];
  const options = names.length ? names : fallbackNames;
  if (!options.includes(settings.aiModel)) settings.aiModel = aiServerState.defaultModel || options[0];
  els.aiModelSelect.innerHTML = options.map(name => `<option value="${escapeAttr(name)}">${escapeHtml(name)}</option>`).join("");
  els.aiModelSelect.value = settings.aiModel;
}

export function renderAiSummaryStatus() {
  if (!els.aiSummaryStatus) return;
  const selected = state.articles.filter(article => article.included);
  const currentSignature = getSummaryInputSignature();
  const modelChanged = !!state.summaryModel && state.summaryModel !== settings.aiModel;
  const stale = ["ai", "ai-edited"].includes(state.summaryMode) && !!state.summaryInputSignature && (state.summaryInputSignature !== currentSignature || modelChanged);
  const coverage = state.summaryCoverage;

  els.aiModelSelect.value = [...els.aiModelSelect.options].some(option => option.value === settings.aiModel) ? settings.aiModel : els.aiModelSelect.value;
  els.aiModelSelect.disabled = isAnalyzingSummary || !aiServerState.online;
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
  } else if (aiServerState.online && AI_SESSION_TOKEN) {
    els.aiConnectionState.classList.add("online");
    els.aiConnectionState.textContent = "Ollama 로컬 연결";
  } else {
    els.aiConnectionState.classList.add("offline");
    els.aiConnectionState.textContent = aiServerState.online ? "실행 인증 필요" : "AI 도우미 오프라인";
  }

  els.aiSummaryStatus.className = "ai-summary-status no-print";
  if (isAnalyzingSummary) {
    els.aiSummaryStatus.classList.add("busy");
    els.aiSummaryStatus.textContent = `${settings.aiModel}이 선정 기사 ${Math.min(selected.length, 20)}건의 본문을 수집하고 경영메시지를 분석 중입니다. 첫 실행은 수 분이 걸릴 수 있습니다.`;
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
    els.aiSummaryStatus.textContent = `${formatDateTime(state.summaryGeneratedAt)} 생성 · ${state.summaryModel} · 선정 ${state.summarySelectedCount}건${confidence}${edited}`;
  } else if (!selected.length) {
    els.aiSummaryStatus.textContent = "먼저 브리핑에 사용할 기사를 선택해 주세요.";
  } else if (!aiServerState.online || !AI_SESSION_TOKEN) {
    els.aiSummaryStatus.textContent = "start_kesco_briefing.command를 실행해 이 화면을 다시 열면 로컬 Gemma 4 분석을 사용할 수 있습니다.";
  } else {
    els.aiSummaryStatus.textContent = `선정 기사 ${selected.length}건이 준비됐습니다. Gemma 4 경영메시지 생성을 실행하세요.`;
  }

  els.generateAiSummaryBtn.disabled = isAnalyzingSummary || !selected.length || !aiServerState.online || !AI_SESSION_TOKEN;
  els.ruleSummaryBtn.disabled = isAnalyzingSummary;
  els.generateAiSummaryBtn.innerHTML = isAnalyzingSummary ? '<span class="spinner"></span><span>Gemma 4 분석 중</span>' : "Gemma 4 경영메시지 생성";
  els.generateAiSummaryBtn.title = !AI_SESSION_TOKEN ? "원클릭 실행 파일로 화면을 열어 주세요." : !selected.length ? "브리핑 기사를 먼저 선택해 주세요." : "선정 기사 본문과 RSS 요약을 분석합니다.";
}

export async function generateAiManagementSummary() {
  const selectedAll = state.articles.filter(article => article.included).sort(relevanceSort);
  if (!selectedAll.length) { showToast("브리핑에 사용할 기사를 먼저 선택해 주세요.", "error"); return; }
  if (!aiServerState.online || !AI_SESSION_TOKEN) { state.summaryError = "AI 도우미가 연결되지 않았습니다. 원클릭 실행 파일로 다시 열어 주세요."; renderSummary(); return; }

  const selected = selectedAll.slice(0, 20);
  const requestId = nextAiRequestSerial();
  aiAbortController?.abort();
  setAiAbortController(new AbortController());
  const requestDate = state.date;
  const inputSignature = getSummaryInputSignature();
  const originalSummary = state.summary;
  state.summaryError = "";
  setAnalyzingSummary(true);
  renderSummary();
  if (selectedAll.length > 20) showToast("관련도순 상위 20건을 AI 분석에 사용합니다.");

  try {
    const articles = selected.map((article, index) => {
      const relevance = getRelevance(article);
      return {
        id: `A${String(index + 1).padStart(2, "0")}`,
        title: article.title,
        source: article.source,
        url: article.url,
        pubDate: article.pubDate,
        description: article.description || "",
        note: article.note || "",
        relevance: relevance.rank < 99 ? `${relevance.rank}순위 · ${relevance.reasons.join(" · ")}` : "지정 기준 외",
        risk: RISK_LABELS[article.risk] || article.risk,
        starred: !!article.starred
      };
    });
    const response = await fetchWithTimeout(`${AI_API_BASE}/analyze`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        "X-KESCO-App": "kesco-media-briefing-v1",
        "X-KESCO-Token": AI_SESSION_TOKEN
      },
      signal: aiAbortController.signal,
      body: JSON.stringify({ model: settings.aiModel, date: state.date, preparedBy: state.preparedBy || "", articles })
    }, 600_000);
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.ok) throw new Error(data.error || `AI 분석 응답 ${response.status}`);
    if (requestId !== aiRequestSerial) return;
    if (state.date !== requestDate || getSummaryInputSignature() !== inputSignature || state.summary !== originalSummary) {
      throw new Error("분석 중 선정 기사·메모 또는 메시지가 변경되어 결과를 적용하지 않았습니다. 다시 실행해 주세요.");
    }

    state.aiAnalysis = data.analysis;
    state.summaryEvidenceMap = Array.isArray(data.articles) ? data.articles.map(article => ({
      id: article.id,
      title: article.title,
      source: article.source,
      basis: article.basis,
      error: article.error || ""
    })) : [];
    state.summary = formatAiAnalysis(data.analysis, state.summaryEvidenceMap);
    state.summaryEdited = false;
    state.summaryMode = "ai";
    state.summaryModel = data.model || settings.aiModel;
    state.summaryGeneratedAt = data.generatedAt || new Date().toISOString();
    state.summaryInputSignature = inputSignature;
    state.summarySelectedCount = selected.length;
    state.summaryEvidenceIds = selected.map((_, index) => `A${String(index + 1).padStart(2, "0")}`);
    state.summaryCoverage = data.stats || null;
    state.summaryError = "";
    saveDailyState();
    showToast(`Gemma 4가 선정 기사 ${selected.length}건을 분석했습니다.`, "success");
  } catch (error) {
    if (requestId !== aiRequestSerial) return;
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
  const lines = [analysis.managementMessage || "핵심 경영메시지를 생성하지 못했습니다."];
  if (analysis.situationSummary) lines.push("", "■ 핵심 상황", analysis.situationSummary);
  if (analysis.keyIssues?.length) {
    lines.push("", "■ 핵심 이슈");
    analysis.keyIssues.forEach((issue, index) => {
      const evidence = issue.articleIds?.length ? ` [근거 ${issue.articleIds.join(", ")}]` : "";
      lines.push(`${index + 1}. ${issue.title} (${issue.urgency})${evidence}`, `   ${issue.summary}`, `   경영 영향: ${issue.managementImpact}`);
    });
  }
  if (analysis.decisionPoints?.length) {
    lines.push("", "■ 경영 판단 포인트");
    analysis.decisionPoints.forEach(point => lines.push(`• ${point}`));
  }
  if (analysis.actionItems?.length) {
    lines.push("", "■ 확인·지시 필요사항");
    analysis.actionItems.forEach(item => {
      const evidence = item.articleIds?.length ? ` [근거 ${item.articleIds.join(", ")}]` : "";
      lines.push(`• [${item.priority}] ${item.action}${evidence}`);
    });
  }
  if (analysis.riskOutlook) lines.push("", "■ 위험 전망", analysis.riskOutlook);
  if (analysis.limitations?.length) lines.push("", `※ 분석 한계: ${analysis.limitations.join(" · ")}`);
  if (evidenceMap.length) {
    lines.push("", "■ 근거 기사");
    evidenceMap.forEach(article => lines.push(`${article.id}. ${article.title} (${article.source || "출처 미상"} · ${article.basis || "근거 미상"})`));
  }
  return lines.join("\n");
}

export function getSummaryInputSignature() {
  const selected = state.articles.filter(article => article.included).sort(relevanceSort).slice(0, 20).map(article => ({
    article,
    stableKey: canonicalArticleUrl(article.url) || normalizedArticleTitle(article.title) || String(article.id || "")
  })).sort((a, b) => a.stableKey.localeCompare(b.stableKey, "ko"));
  const raw = JSON.stringify({
    preparedBy: state.preparedBy || "",
    articles: selected.map(({ article, stableKey }) => [stableKey, article.title, article.source, article.url, article.pubDate, article.description || "", article.note || "", article.risk, !!article.starred])
  });
  let hash = 2166136261;
  for (let index = 0; index < raw.length; index += 1) {
    hash ^= raw.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return `v2-${(hash >>> 0).toString(16)}-${selected.length}`;
}
