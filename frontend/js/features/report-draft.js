import { $, state, flushDailyState } from "../state/store.js";
import * as api from "../api/client.js?v=20260721-1";
import { downloadBlob } from "../utils/dom.js";
import { escapeAttr, escapeHtml, friendlyError, safeUrl } from "../utils/strings.js";
import { openOverlay, closeOverlay } from "../ui/dialogs.js";
import { showToast } from "../ui/notifications.js?v=20260716-1";
import { flushArticleChanges, focusRelatedEvidence, renderArticles } from "./articles.js?v=20260721-1";

let currentSignature = "";
let currentSourceType = "manual";
let currentEvidenceIds = [];

function emptyContent() {
  return {
    managementMessage: { text: "", articleIds: [] },
    situationSummary: { text: "", articleIds: [] },
    keyIssues: [], decisionPoints: [], actionItems: [],
    riskOutlook: { text: "", articleIds: [], isInference: true },
    limitations: [], confidence: "medium"
  };
}

function contentFromText(text) {
  return {
    managementMessage: { text: String(text || "").trim(), articleIds: currentEvidenceIds },
    situationSummary: { text: "", articleIds: [] },
    keyIssues: [], decisionPoints: [], actionItems: [],
    riskOutlook: { text: "", articleIds: [], isInference: true },
    limitations: [], confidence: "medium"
  };
}

function setEditorContent(content) {
  const value = content || emptyContent();
  const references = (value.keyIssues || [])
    .filter(item => item.urgency === "reference")
    .map(item => [item.summary, item.managementImpact].filter(Boolean).join(" ").trim())
    .filter(Boolean);
  $("reportDraftContent").value = [
    "① 오늘의 핵심",
    value.managementMessage?.text || "",
    "② 경영 시사점",
    value.situationSummary?.text || "",
    "③ 참고 동향",
    references.length ? references.join("\n\n") : "별도 참고 동향 없음."
  ].join("\n\n");
}

function setDraftStatus(message, tone = "") {
  const status = $("reportDraftStatus");
  status.textContent = message;
  status.className = `report-draft-status ${tone}`.trim();
}

async function syncPendingChanges() {
  await flushArticleChanges();
  await flushDailyState();
}

export async function downloadAnalysisMarkdown() {
  if (!state.articles.some(article => article.included)) {
    showToast("브리핑에 선정한 기사가 없습니다.", "error");
    return;
  }
  try {
    await syncPendingChanges();
    showToast("선정 기사 전문을 확인해 Markdown을 만들고 있습니다.");
    const markdown = await api.getAnalysisMarkdown(state.date);
    const issuesResult = await api.listIssues(state.date);
    state.issues = issuesResult.data.issues || [];
    renderArticles();
    downloadBlob(markdown, `KESCO_AI분석자료_${state.date}.md`, "text/markdown;charset=utf-8");
    showToast("고성능 AI 분석용 Markdown을 저장했습니다.", "success");
  } catch (error) {
    if (error.code === "SELECTED_EVIDENCE_INVALID") {
      showEvidenceValidationFailure(error);
      return;
    }
    showToast(`Markdown 내보내기 실패: ${friendlyError(error)}`, "error");
  }
}

function showEvidenceValidationFailure(error) {
  const articles = error.details?.failedArticles || [];
  const list = $("evidenceFailureList");
  $("evidenceFailureSummary").textContent = `선택한 기사 중 근거 상태를 확인해야 하는 기사가 ${articles.length}건 있습니다.`;
  list.innerHTML = articles.map((article, index) => {
    const messages = (article.errors || []).map(item => item.message).join(" · ") || "기사 근거를 확인해 주세요.";
    const href = safeUrl(article.url);
    return `<article class="evidence-failure-item" data-article-id="${escapeAttr(article.articleId)}" data-issue-id="${escapeAttr(article.issueId || "")}">
      <strong>${index + 1}. ${escapeHtml(article.title)}</strong><p>${escapeHtml(messages)}</p>
      <div class="evidence-failure-actions">${article.issueId ? '<button class="btn btn-primary" data-action="select-related" type="button">관련기사 선택</button>' : ""}<button class="btn" data-action="reextract" type="button">본문 다시 추출</button>${href ? `<a class="btn" href="${escapeAttr(href)}" target="_blank" rel="noopener noreferrer">원문 확인</a>` : ""}</div>
    </article>`;
  }).join("");
  list.onclick = async event => {
    const action = event.target.closest("[data-action]")?.dataset.action;
    const item = event.target.closest(".evidence-failure-item");
    if (!action || !item) return;
    if (action === "select-related") {
      closeOverlay("evidenceFailureOverlay");
      focusRelatedEvidence(item.dataset.issueId, item.dataset.articleId);
      return;
    }
    if (action === "reextract") {
      event.target.disabled = true;
      try {
        const result = await api.reextractArticle(item.dataset.articleId);
        const issuesResult = await api.listIssues(state.date);
        state.issues = issuesResult.data.issues || [];
        renderArticles();
        showToast(result.data.analysisEligible ? "본문 재추출 후 근거 검증을 통과했습니다." : "재추출했지만 다른 관련기사를 선택해야 합니다.", result.data.analysisEligible ? "success" : "");
      } catch (reextractError) {
        showToast(`본문 재추출 실패: ${friendlyError(reextractError)}`, "error");
      } finally {
        event.target.disabled = false;
      }
    }
  };
  openOverlay("evidenceFailureOverlay");
}

export async function openReportDraftEditor() {
  try {
    await syncPendingChanges();
    const result = await api.getReportDraft(state.date);
    const { draft, inputSignature, evidence, selectedCount } = result.data;
    currentSignature = inputSignature;
    currentEvidenceIds = Object.keys(evidence || {});
    currentSourceType = draft?.sourceType || "manual";
    $("reportDraftSource").value = draft?.sourceLabel || "";
    $("externalAnalysisPaste").value = "";
    setEditorContent(draft?.content || state.aiAnalysis || emptyContent());
    const ids = currentEvidenceIds.join(", ") || "없음";
    setDraftStatus(draft
      ? `${draft.sourceLabel || "CEO 보고 편집본"} · 근거 ${ids}${draft.stale ? " · 선정 기사 변경됨" : ""}`
      : `저장된 편집본 없음 · 선정 ${selectedCount}건 · 사용 가능 근거 ${ids}`,
    draft?.stale ? "stale" : "");
    const finalized = state.status === "final";
    ["reportDraftContent", "externalAnalysisPaste", "reportDraftSource"].forEach(id => { $(id).disabled = finalized; });
    $("validateExternalAnalysisBtn").disabled = finalized;
    $("loadGemmaDraftBtn").disabled = finalized || !state.aiAnalysis;
    $("saveReportDraftBtn").disabled = finalized;
    openOverlay("reportDraftOverlay");
  } catch (error) {
    showToast(`CEO 보고 편집본 불러오기 실패: ${friendlyError(error)}`, "error");
  }
}

export async function validateExternalAnalysis() {
  try {
    const text = $("externalAnalysisPaste").value.trim();
    if (!text) throw new Error("붙여넣은 외부 AI 분석 텍스트가 없습니다.");
    setDraftStatus("외부 AI 결과의 형식과 근거를 확인하고 있습니다…");
    const result = await api.validateReportDraft(state.date, {
      reportDate: state.date,
      inputSignature: currentSignature,
      sourceLabel: $("reportDraftSource").value.trim(),
      text
    });
    currentSignature = result.data.inputSignature;
    currentEvidenceIds = Object.keys(result.data.evidence || {});
    currentSourceType = "external";
    if (!$("reportDraftSource").value.trim()) $("reportDraftSource").value = result.data.sourceLabel || "외부 고성능 AI";
    setEditorContent(result.data.content);
    setDraftStatus(`텍스트 반영 완료 · 선정 기사 ${currentEvidenceIds.length}건을 근거로 연결합니다.`, "ready");
    showToast("외부 AI 결과를 CEO 보고 편집 폼에 불러왔습니다.", "success");
  } catch (error) {
    const reason = error.details?.reason ? ` (${error.details.reason})` : "";
    setDraftStatus(`검증 실패: ${friendlyError(error)}${reason}`, "error");
  }
}

export function loadGemmaDraft() {
  if (!state.aiAnalysis) return showToast("불러올 Gemma 분석 결과가 없습니다.", "error");
  currentSourceType = "gemma";
  $("reportDraftSource").value = state.summaryModel || "Gemma 4";
  setEditorContent(state.aiAnalysis);
  setDraftStatus("Gemma 분석 결과를 편집 폼에 불러왔습니다. 저장 전 내용을 수정할 수 있습니다.", "ready");
}

export async function saveReportDraft() {
  try {
    const reportText = $("reportDraftContent").value.trim();
    if (!reportText) throw new Error("저장할 CEO 보고 분석 내용이 없습니다.");
    const content = contentFromText(reportText);
    const result = await api.putReportDraft(state.date, {
      expectedRevision: state.revision,
      sourceType: ["external", "gemma"].includes(currentSourceType) ? currentSourceType : "manual",
      sourceLabel: $("reportDraftSource").value.trim(),
      inputSignature: currentSignature,
      content,
      basedOnAiRunId: null
    });
    state.revision = result.data.revision;
    currentSourceType = result.data.draft.sourceType;
    setDraftStatus(`${result.data.draft.sourceLabel || "CEO 보고 편집본"} · 저장 완료`, "ready");
    showToast("CEO 보고 편집본을 저장했습니다. 미리보기에 반영됩니다.", "success");
  } catch (error) {
    const reason = error.details?.reason ? ` (${error.details.reason})` : "";
    setDraftStatus(`저장 실패: ${friendlyError(error)}${reason}`, "error");
  }
}

export function previewFromDraftEditor() {
  window.open(`/preview/${encodeURIComponent(state.date)}`, "_blank", "noopener");
}

export function closeReportDraftEditor() {
  closeOverlay("reportDraftOverlay");
}
