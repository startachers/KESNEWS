import { els, loadDailyState, setState, settings, state } from "../state/store.js";
import * as api from "../api/client.js";
import { renderAll } from "../ui/renderers.js";
import { showToast } from "../ui/notifications.js?v=20260716-1";
import { escapeHtml, friendlyError } from "../utils/strings.js";

let recommendationRun = null;
let running = false;

function setBusy(value) {
  running = value;
  els.autoSelectBtn.setAttribute("aria-busy", String(value));
  els.autoSelectBtn.disabled = value || state.status === "final" || !state.articles.length;
  els.autoSelectBtn.textContent = value ? "Gemma 추천 분석 중…" : "Gemma 추천 12건";
}

function renderRecommendations(run) {
  const recommendations = run?.response?.recommendations || [];
  const requiredLabels = run?.request?.requiredTopicLabels || [];
  const quotaText = requiredLabels.length ? ` · 필수 분야 ${requiredLabels.join("·")}` : "";
  els.autoSelectionMeta.textContent = `현재 선정 ${state.articles.filter(article => article.included).length}건 · Gemma 추천 ${recommendations.length}건 · ${run.model}${quotaText}`;
  els.autoSelectionList.innerHTML = recommendations.map(item => `
    <article class="auto-selection-item">
      <span class="auto-selection-rank">${item.rank}</span>
      <div>
        <strong>${escapeHtml(item.title || "제목 없음")}</strong>
        <small>${escapeHtml(item.source || "출처 미상")} · ${item.rank <= 6 ? "핵심 선정" : "추가 참고"}</small>
        <p><b>기사 사실</b> ${escapeHtml(item.articleFact || item.reason || "-")}</p>
        <p><b>공사 연관성</b> ${escapeHtml(item.kescoRelevance || "-")}</p>
        <p><b>선정 이유</b> ${escapeHtml(item.selectionReason || item.reason || "-")}</p>
      </div>
    </article>
  `).join("");
  const limitations = run?.response?.limitations || [];
  els.autoSelectionLimitations.hidden = !limitations.length;
  els.autoSelectionLimitations.textContent = limitations.length ? `분석 한계: ${limitations.join(" · ")}` : "";
  els.autoSelectionApplyBtn.disabled = !recommendations.length || state.status === "final";
}

export async function openAutoSelectionProposal() {
  if (running || state.status === "final") return;
  if (state.articles.filter(article => article.included).length >= 12) {
    showToast("이미 브리핑 기사가 12건 이상 선정되어 있습니다.", "error");
    return;
  }
  setBusy(true);
  try {
    const result = await api.recommendBriefingArticles(
      state.date,
      state.revision,
      settings.aiModel || "gemma4:26b",
    );
    recommendationRun = result.data.run;
    renderRecommendations(recommendationRun);
    els.autoSelectionOverlay.classList.add("open");
    showToast("Gemma 추천 결과를 만들었습니다. 적용 전 내용을 확인해 주세요.", "success");
  } catch (error) {
    showToast(`기사 추천 실패: ${friendlyError(error)}`, "error");
  } finally {
    setBusy(false);
  }
}

export async function applyAutoSelectionProposal() {
  if (!recommendationRun || state.status === "final") return;
  els.autoSelectionApplyBtn.disabled = true;
  try {
    const result = await api.applyBriefingArticleRecommendations(
      state.date,
      state.revision,
      recommendationRun.id,
    );
    setState(await loadDailyState(state.date));
    renderAll();
    els.autoSelectionOverlay.classList.remove("open");
    showToast(`Gemma 추천 기사 ${result.data.appliedArticleIds.length}건을 추가하고 Top Issues ${result.data.topIssueArticleIds?.length || 0}칸을 채웠습니다.`, "success");
    recommendationRun = null;
  } catch (error) {
    if (["BRIEFING_REVISION_CONFLICT", "AI_INPUT_STALE"].includes(error.code)) {
      setState(await loadDailyState(state.date));
      renderAll();
    }
    showToast(`추천 적용 실패: ${friendlyError(error)}`, "error");
    els.autoSelectionApplyBtn.disabled = false;
  }
}

export function closeAutoSelectionProposal() {
  if (!running) els.autoSelectionOverlay.classList.remove("open");
}
