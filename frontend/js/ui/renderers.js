import { $, state, settings, els, isSearching } from "../state/store.js";
import { escapeHtml, shortText } from "../utils/strings.js";
import { formatDateTime, formatTime, localDateKey } from "../utils/dates.js";
import { renderSummary } from "../features/ai-analysis.js";
import { renderTopIssues } from "../features/issues.js?v=20260720-2";
import { renderArticles } from "../features/articles.js?v=20260720-6";
import { renderWeather } from "../features/weather.js";

export function renderAll() {
  renderHeader();
  renderMetrics();
  renderWeather();
  renderSummary();
  renderTopIssues();
  renderArticles();
  renderSidePanel();
}

export function renderHeader() {
  const d = new Date(`${state.date}T12:00:00`);
  const ko = new Intl.DateTimeFormat("ko-KR", { year: "numeric", month: "2-digit", day: "2-digit" }).format(d).replace(/\. /g, ". ").replace(/\.$/, "");
  const day = new Intl.DateTimeFormat("en-US", { weekday: "long" }).format(d).toUpperCase();
  els.mastheadDate.textContent = ko;
  els.mastheadDay.textContent = `${day} · CEO BRIEF`;
  els.reportDate.value = state.date;
  els.preparedBy.value = state.preparedBy || "";
  els.report.classList.toggle("demo-mode", !!state.demo);
  const finalized = state.status === "final";
  document.body.classList.toggle("finalized", finalized);
  els.preparedBy.disabled = finalized;
  els.summaryEditor.disabled = finalized;
  els.actionNote.disabled = finalized;
  els.refreshBtn.disabled = finalized;
  els.reclusterBtn.disabled = finalized || isSearching || state.demo || !state.articles.length;
  const selectionFull = state.articles.filter(article => article.included).length >= 12;
  els.autoSelectBtn.disabled = finalized || isSearching || state.demo || !state.articles.length || selectionFull;
  els.autoSelectBtn.title = selectionFull ? "이미 브리핑 기사가 12건 이상 선정되어 있습니다." : "공사 관련성을 우선해 핵심 6건과 참고 6건을 추천합니다.";
  $("addArticleBtn").disabled = finalized;
  $("importBtn").disabled = finalized;
  $("resetTodayBtn").disabled = finalized || isSearching || state.date !== localDateKey();
  els.finalizeBtn.hidden = finalized;
  els.reopenBtn.hidden = !finalized;
  els.finalReportBtn.hidden = !state.latestFinalVersion;
  els.briefingState.textContent = finalized
    ? `최종 확정 v${state.latestFinalVersion} · 수정하려면 작업본을 다시 여세요.`
    : state.latestFinalVersion
      ? `수정 중 · 최종본 v${state.latestFinalVersion}은 보존됩니다.`
      : "작성 중 · 아직 최종 확정되지 않았습니다.";
}

export function renderMetrics() {
  const items = state.articles;
  const priorityIssues = state.issues.filter(issue => (issue.effectiveReviewStars || 0) >= 4).length;
  const sources = new Set(items.map(a => a.source).filter(Boolean)).size;
  els.kpiTotal.innerHTML = `${items.length}<small>건</small>`;
  els.kpiRisk.innerHTML = `${priorityIssues}<small>개</small>`;
  els.kpiPositive.innerHTML = `${state.issues.length}<small>개</small>`;
  els.kpiSources.innerHTML = `${sources}<small>개</small>`;
  els.kpiTotalNote.textContent = state.fetchedAt ? `${settings.lookback}시간 · 원본 후보 ${state.rawCollectedCount || items.length}건` : "검색 대기";
  const selected = items.filter(a => a.included).length;
  const issueNote = state.issues.length ? ` · 이슈 ${state.issues.length}개` : "";
  els.kpiSourceNote.textContent = items.length ? `${selected}건 브리핑 선정 · 중복 ${state.duplicatesRemoved || 0}건 제거${issueNote}` : "유사 제목·동일 URL 자동 정리";
  const counts = { 1: 0, 2: 0, 3: 0, 4: 0, 5: 0 };
  state.issues.forEach(issue => { const stars = issue.effectiveReviewStars || 1; counts[stars] += 1; });
  const max = Math.max(state.issues.length, 1);
  [5, 4, 3, 2, 1].forEach(stars => { els[`star${stars}Count`].textContent = counts[stars]; els[`star${stars}Bar`].style.width = `${Math.round(counts[stars] / max * 100)}%`; });
}

export function renderSidePanel() {
  els.footerTimestamp.textContent = state.lastRunStatus === "error" && state.lastAttemptAt
    ? `${formatDateTime(state.lastAttemptAt)} 수집 시도 실패`
    : state.fetchedAt ? `${formatDateTime(state.fetchedAt)} 수집` : "수집 전";
  const providerLabel = state.provider || "연합뉴스 RSS 우선 · Google 뉴스 보완";
  els.sourceStateBox.classList.remove("error", "warning");
  if (isSearching) {
    els.sourceStateTitle.textContent = "기사 검색 중";
    els.sourceStateDetail.textContent = "검색식별 수집·중복 제거 중";
  } else if (state.lastRunStatus === "error") {
    els.sourceStateBox.classList.add("error");
    els.sourceStateTitle.textContent = "수집 실패 · 다시 시도 가능";
    els.sourceStateDetail.textContent = state.errors[0] ? shortText(state.errors[0], 92) : "데이터 서버 연결을 확인해 주세요.";
  } else if (state.fetchedAt) {
    if (state.warnings?.length) els.sourceStateBox.classList.add("warning");
    els.sourceStateTitle.textContent = `${formatTime(state.fetchedAt)} 수집 완료`;
    const stats = state.sourceFilterStats;
    const sourceSummary = stats
      ? ` · 출처 허용 ${Number(stats.official_sources || 0) + Number(stats.trusted_media || 0)}건 / 제외 ${Number(stats.rejected_untrusted_media || 0)}건`
      : "";
    els.sourceStateDetail.textContent = `${state.naverStatus} · ${providerLabel} · 원본 ${state.rawCollectedCount || state.articles.length}건${sourceSummary} → 중복 ${state.duplicatesRemoved || 0}건 제거 → 최종 ${state.articles.length}건`;
  } else {
    els.sourceStateTitle.textContent = "검색 대기";
    els.sourceStateDetail.textContent = providerLabel;
  }
  const diagnostics = state.errors?.length ? state.errors : (state.warnings || []);
  els.collectionErrors.hidden = !diagnostics.length;
  els.collectionErrors.open = !!state.errors?.length;
  els.collectionErrorsSummary.textContent = state.errors?.length ? `수집 오류 ${state.errors.length}건` : `일부 검색 알림 ${diagnostics.length}건`;
  els.collectionErrorsList.innerHTML = diagnostics.map(message => `<li>${escapeHtml(message)}</li>`).join("");
  els.keywordCloud.innerHTML = settings.coreKeywords.concat(settings.riskKeywords.slice(0,5)).map(k => `<span class="keyword-chip">${escapeHtml(k)}</span>`).join("");
}
