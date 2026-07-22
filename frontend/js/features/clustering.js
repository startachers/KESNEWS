import { els, state } from "../state/store.js";
import * as api from "../api/client.js";
import { closeOverlay, openOverlay } from "../ui/dialogs.js";
import { setStatus, showToast } from "../ui/notifications.js?v=20260716-1";
import { renderAll } from "../ui/renderers.js";
import { escapeHtml, friendlyError } from "../utils/strings.js";

const STATUS_LABELS = { new: "신규", expanding: "확산", ongoing: "지속", cooling: "진정", closed: "종료" };
function starsText(value) { const stars = Math.max(1, Math.min(5, Number(value) || 1)); return `${"★".repeat(stars)}${"☆".repeat(5 - stars)}`; }

let activeRun = null;
let busy = false;
let thresholdDirty = true;

function thresholdValue() {
  return Number(els.clusterThreshold.value) / 100;
}

function appliedThresholdPercent() {
  const threshold = state.issues
    .map(issue => issue.autoReasons?.clustering?.pairThreshold)
    .find(Number.isFinite);
  return Number.isFinite(threshold) ? Math.round(threshold * 100) : 40;
}

function thresholdHint(percent, dirty = false) {
  const guidance = percent <= 35
    ? "같은 사건으로 볼 수 있는 기사를 넓게 묶습니다."
    : percent >= 55
      ? "제목과 사건 단서가 매우 가까운 기사만 묶습니다."
      : "비슷한 제목과 사건 단서를 균형 있게 반영합니다.";
  return dirty ? `${guidance} 변경한 기준으로 다시 계산해야 적용할 수 있습니다.` : guidance;
}

function renderThreshold(dirty = thresholdDirty) {
  const percent = Number(els.clusterThreshold.value);
  els.clusterThresholdValue.textContent = `${percent}%`;
  els.clusterThresholdHint.textContent = thresholdHint(percent, dirty);
}

function setBusy(value, mode = "") {
  busy = value;
  els.reclusterBtn.disabled = value || state.status === "final" || state.demo || !state.articles.length;
  els.reclusterBtn.textContent = value && mode === "calculate" ? "제안 생성 중…" : "이슈 다시 그룹화";
  els.clusterThreshold.disabled = value;
  els.clusterRecalculateBtn.disabled = value || !thresholdDirty;
  els.clusterRecalculateBtn.textContent = value && mode === "calculate" ? "계산 중…" : "이 기준으로 다시 계산";
  els.clusterApplyBtn.disabled = value || thresholdDirty || !(activeRun?.proposal?.length);
  els.clusterApplyBtn.textContent = value && mode === "apply" ? "적용 중…" : "제안 적용";
}

function renderProposal(run) {
  const proposal = run.proposal || [];
  const diff = run.diff || {};
  const articleById = new Map(state.articles.map(article => [article.id, article]));
  const groupedCount = proposal.filter(issue => issue.articleIds?.length > 1).length;
  const articleCount = proposal.reduce((total, issue) => total + (issue.articleIds?.length || 0), 0);

  const appliedThreshold = proposal[0]?.autoReasons?.clustering?.pairThreshold;
  const thresholdLabel = Number.isFinite(appliedThreshold) ? ` · 유사도 ${Math.round(appliedThreshold * 100)}%` : "";
  els.clusterProposalMeta.innerHTML = `<strong>${escapeHtml(state.date)}</strong> 기사 ${articleCount}건을 ${proposal.length}개 이슈로 제안했습니다.${thresholdLabel} · ${escapeHtml(run.algorithmVersion || "알고리즘 정보 없음")} · 복수 기사 이슈 ${groupedCount}개`;
  els.clusterDiffSummary.innerHTML = [
    ["새 이슈", diff.createdIssues?.length || 0],
    ["기존 이슈 병합 검토", diff.mergeCandidates?.length || 0],
    ["기존 이슈 분할 검토", diff.splitCandidates?.length || 0],
    ["구성 변경 기사", diff.movedArticles?.length || 0],
    ["수동 수정 보존", diff.preservedEditorOverrides?.length || 0],
  ].map(([label, count]) => `<span class="cluster-stat">${label} <strong>${count}</strong></span>`).join("");

  els.clusterProposalList.innerHTML = proposal.length ? proposal.map((issue, index) => {
    const articleIds = issue.articleIds || [];
    const grouped = articleIds.length > 1;
    const pressCoverage = issue.autoReasons?.origin?.type === "kesco_press_release";
    const members = articleIds.map(articleId => {
      const article = articleById.get(articleId);
      return `<li><strong>${escapeHtml(article?.title || articleId)}</strong>${article?.source ? ` · ${escapeHtml(article.source)}` : ""}</li>`;
    }).join("");
    return `<article class="cluster-proposal ${grouped ? "grouped" : ""}">
      <div class="cluster-proposal-head">
        <div><span class="cluster-proposal-rank">ISSUE ${String(index + 1).padStart(2, "0")}</span><h3>${escapeHtml(issue.autoTitle || "제목 없음")}</h3></div>
        <div class="cluster-badges">${pressCoverage ? '<span class="cluster-badge press-origin">보도자료 확산</span>' : ""}<span class="cluster-badge ${grouped ? "grouped" : ""}">${grouped ? `동일 이슈 ${articleIds.length}건` : "단일 기사"}</span><span class="cluster-badge">${escapeHtml(STATUS_LABELS[issue.autoStatus] || issue.autoStatus || "상태 없음")}</span><span class="cluster-badge review-stars">${starsText(issue.autoReviewStars)} · ${issue.autoReviewRank || "-"}위 · ${issue.autoReviewScore ?? "-"}점</span></div>
      </div>
      <ul class="cluster-members">${members}</ul>
    </article>`;
  }).join("") : '<div class="cluster-empty">그룹화할 기사 후보가 없습니다.</div>';
  els.clusterApplyBtn.disabled = thresholdDirty || !proposal.length;
}

async function calculateProposal() {
  if (busy) return;
  setBusy(true, "calculate");
  setStatus("busy", "동일 사건 기사 묶음을 계산하는 중…");
  try {
    const result = await api.createClusterRun(state.date, thresholdValue());
    activeRun = result.data;
    thresholdDirty = false;
    renderThreshold(false);
    renderProposal(activeRun);
    setStatus("live", `${activeRun.proposal.length}개 이슈 제안 생성 · 적용 전`);
  } catch (error) {
    showToast(`그룹 변경 제안 실패: ${friendlyError(error)}`, "error");
    setStatus("error", "그룹 변경 제안을 만들지 못했습니다");
  } finally {
    setBusy(false);
  }
}

export function handleClusterThresholdInput() {
  if (busy) return;
  thresholdDirty = true;
  renderThreshold(true);
  setBusy(false);
}

export async function recalculateClusterProposal() {
  if (!thresholdDirty) return;
  await calculateProposal();
}

export async function openClusterProposal() {
  if (busy) return;
  if (state.status === "final") {
    showToast("최종 확정된 작업본입니다. 수정 재개 후 다시 그룹화해 주세요.", "error");
    return;
  }
  if (state.demo || !state.articles.length) {
    showToast("실제 기사를 수집하거나 등록한 뒤 다시 그룹화해 주세요.", "error");
    return;
  }
  activeRun = null;
  thresholdDirty = true;
  const initialThreshold = appliedThresholdPercent();
  els.clusterThreshold.value = String(initialThreshold);
  renderThreshold(true);
  els.clusterProposalMeta.textContent = `현재 적용 기준 ${initialThreshold}%로 제안을 계산하고 있습니다.`;
  els.clusterDiffSummary.innerHTML = "";
  els.clusterProposalList.innerHTML = '<div class="cluster-empty">기사 묶음을 계산하는 중…</div>';
  openOverlay("clusterOverlay");
  await calculateProposal();
}

export async function applyClusterProposal() {
  if (busy || thresholdDirty || !activeRun) return;
  setBusy(true, "apply");
  try {
    await api.applyClusterRun(activeRun.id);
    const issueCount = activeRun.proposal?.length || 0;
    const issuesResult = await api.listIssues(state.date);
    state.issues = issuesResult.data.issues || [];
    renderAll();
    activeRun = null;
    closeOverlay("clusterOverlay");
    showToast(`${issueCount}개 이슈 구성을 적용했습니다. 기사 원문과 수동 수정은 보존됩니다.`, "success");
    setStatus("live", `${issueCount}개 이슈 그룹 변경 적용 완료`);
  } catch (error) {
    if (error.code === "CLUSTER_RUN_STALE") {
      activeRun = null;
      closeOverlay("clusterOverlay");
      showToast("제안 생성 후 기사 후보가 변경됐습니다. 그룹화를 다시 실행해 주세요.", "error");
    } else {
      showToast(`그룹 변경 적용 실패: ${friendlyError(error)}`, "error");
    }
    setStatus("error", "그룹 변경 제안을 적용하지 못했습니다");
  } finally {
    setBusy(false);
  }
}
