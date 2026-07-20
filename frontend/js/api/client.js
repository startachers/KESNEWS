import { AI_API_BASE } from "../state/store.js";
import { fetchWithTimeout } from "../utils/net.js";

const CLUSTER_RUN_TIMEOUT_MS = 120000;
const MANAGEMENT_ANALYSIS_REQUEST_TIMEOUT_MS = 1230000;

async function request(path, options = {}, timeoutMs = 15000) {
  const response = await fetchWithTimeout(
    `${AI_API_BASE}${path}`,
    { headers: { "Content-Type": "application/json", Accept: "application/json", ...(options.headers || {}) }, ...options },
    timeoutMs
  );
  const body = await response.json().catch(() => ({}));
  if (!body.ok) {
    const error = new Error(body?.error?.message || `요청을 처리하지 못했습니다 (${response.status}).`);
    error.code = body?.error?.code;
    error.details = body?.error?.details;
    error.status = response.status;
    throw error;
  }
  return body;
}

export function getBriefing(date) {
  return request(`/briefings/${date}`);
}

export function listBriefings(limit = 100) {
  return request(`/briefings?limit=${encodeURIComponent(limit)}`);
}

export function putBriefing(date, expectedRevision, patch) {
  return request(`/briefings/${date}`, { method: "PUT", body: JSON.stringify({ expectedRevision, patch }) });
}

export function resetTodayWork(date, expectedRevision) {
  return request(`/briefings/${encodeURIComponent(date)}/reset`, {
    method: "POST",
    body: JSON.stringify({ expectedRevision, confirmation: "RESET_TODAY" }),
  }, 30000);
}

export function finalizeBriefing(date, expectedRevision) {
  return request(`/briefings/${date}/finalize`, {
    method: "POST",
    body: JSON.stringify({ expectedRevision }),
  });
}

export function reopenBriefing(date, expectedRevision) {
  return request(`/briefings/${date}/reopen`, {
    method: "POST",
    body: JSON.stringify({ expectedRevision }),
  });
}

export function listBriefingVersions(date) {
  return request(`/briefings/${date}/versions`);
}

export function analyzeBriefing(date, expectedRevision, model, signal) {
  return request(`/briefings/${date}/analyze`, {
    method: "POST",
    body: JSON.stringify({ expectedRevision, model }),
    signal,
  }, MANAGEMENT_ANALYSIS_REQUEST_TIMEOUT_MS);
}

export function cancelBriefingAnalysis(date) {
  return request(`/briefings/${date}/analysis/cancel`, { method: "POST" });
}

export function recommendBriefingArticles(date, expectedRevision, model, signal) {
  return request(`/briefings/${encodeURIComponent(date)}/selection-recommendations`, {
    method: "POST",
    body: JSON.stringify({ expectedRevision, model }),
    signal,
  }, 330000);
}

export function applyBriefingArticleRecommendations(date, expectedRevision, runId) {
  return request(`/briefings/${encodeURIComponent(date)}/selection-recommendations/apply`, {
    method: "POST",
    body: JSON.stringify({ expectedRevision, runId }),
  });
}

export function getReportDraft(date) {
  return request(`/briefings/${encodeURIComponent(date)}/report-draft`);
}

export function validateReportDraft(date, payload) {
  return request(`/briefings/${encodeURIComponent(date)}/report-draft/validate`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function putReportDraft(date, payload) {
  return request(`/briefings/${encodeURIComponent(date)}/report-draft`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function getAnalysisMarkdown(date) {
  const response = await fetchWithTimeout(
    `${AI_API_BASE}/exports/${encodeURIComponent(date)}.md`,
    { method: "POST", headers: { Accept: "text/markdown" } },
    120000
  );
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const error = new Error(body?.error?.message || `Markdown 내보내기 실패 (${response.status})`);
    error.code = body?.error?.code;
    throw error;
  }
  return response.text();
}

export function patchBriefingArticle(date, articleId, expectedRevision, fields) {
  return request(`/briefings/${date}/articles/${articleId}`, {
    method: "PATCH",
    body: JSON.stringify({ expectedRevision, ...fields }),
  });
}

export function putArticleOrder(date, expectedRevision, articleIds) {
  return request(`/briefings/${date}/article-order`, {
    method: "PUT",
    body: JSON.stringify({ expectedRevision, articleIds }),
  });
}

export function listArticles(date, includeDismissed = false) {
  return request(`/articles?report_date=${encodeURIComponent(date)}&include_dismissed=${includeDismissed}`);
}

export function createManualArticle(payload) {
  return request(`/articles`, { method: "POST", body: JSON.stringify(payload) });
}

export function deleteArticle(articleId) {
  return request(`/articles/${articleId}?confirm=true`, { method: "DELETE" });
}

export function patchArticleAssessment(articleId, fields) {
  return request(`/articles/${articleId}/assessment`, {
    method: "PATCH",
    body: JSON.stringify(fields),
  });
}

export function runCollection(payload) {
  return request(`/collections`, { method: "POST", body: JSON.stringify(payload) }, 120000);
}

export function getLatestCollection(date) {
  return request(`/collections/latest?report_date=${encodeURIComponent(date)}`);
}

export function getWeatherBriefing(date) {
  return request(`/weather/briefing?report_date=${encodeURIComponent(date)}`);
}

export function refreshWeather(date) {
  return request(`/weather/refresh`, {
    method: "POST",
    body: JSON.stringify({ reportDate: date }),
  }, 120000);
}

export function putBriefingWeather(date, payload) {
  return request(`/briefings/${encodeURIComponent(date)}/weather`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function getKescoPressStatus() {
  return request(`/kesco-press-releases/status`);
}

export function listKescoPress(limit = 30) {
  return request(`/kesco-press-releases?limit=${encodeURIComponent(limit)}`);
}

export function refreshKescoPress(maxRecords = 30) {
  return request(`/kesco-press-releases/refresh`, {
    method: "POST",
    body: JSON.stringify({ maxRecords }),
  }, 60000);
}

export function restartServer() {
  return request(`/operations/restart`, {
    method: "POST",
    headers: { "X-KESCO-Restart": "confirmed" },
  });
}

export async function getServerProcessId() {
  const response = await fetchWithTimeout(
    `${AI_API_BASE}/health`,
    { headers: { Accept: "application/json" } },
    3000
  );
  const body = await response.json();
  if (!response.ok || body.service !== "kesco-media-briefing") {
    throw new Error("현재 서버 정보를 확인하지 못했습니다.");
  }
  return String(body.instanceId || "").split("-", 1)[0];
}

export async function waitForRestart(previousProcessId, timeoutMs = 45000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    await new Promise(resolve => window.setTimeout(resolve, 500));
    try {
      const response = await fetchWithTimeout(`${AI_API_BASE}/health`, { headers: { Accept: "application/json" } }, 1500);
      const body = await response.json();
      if (response.ok && body.service === "kesco-media-briefing" && !String(body.instanceId || "").startsWith(`${previousProcessId}-`)) return;
    } catch {
      // 기존 서버 종료 중의 연결 실패는 정상적인 재시작 과정이다.
    }
  }
  throw new Error("서버가 45초 안에 다시 시작되지 않았습니다. 로그를 확인해 주세요.");
}

export function createClusterRun(reportDate, similarityThreshold = 0.40) {
  return request(`/cluster-runs`, {
    method: "POST",
    body: JSON.stringify({ reportDate, similarityThreshold }),
  }, CLUSTER_RUN_TIMEOUT_MS);
}

export function listIssues(reportDate) {
  return request(`/issues?report_date=${encodeURIComponent(reportDate)}`);
}

export function patchBriefingIssue(reportDate, issueId, expectedRevision, fields) {
  return request(`/briefings/${encodeURIComponent(reportDate)}/issues/${encodeURIComponent(issueId)}`, {
    method: "PATCH",
    body: JSON.stringify({ expectedRevision, ...fields }),
  });
}

export function removeIssueArticle(reportDate, issueId, articleId, expectedRevision) {
  return patchBriefingIssue(reportDate, issueId, expectedRevision, {
    articleId,
    membershipAction: "remove",
  });
}

export function createManualIssueGroup(reportDate, articleIds, expectedRevision) {
  return request("/issues/manual-group", {
    method: "POST",
    body: JSON.stringify({ reportDate, articleIds, expectedRevision }),
  });
}

export function applyClusterRun(clusterRunId) {
  return request(`/cluster-runs/${encodeURIComponent(clusterRunId)}/apply`, { method: "POST" });
}

export function getJsonExport(date) {
  return request(`/exports/${date}.json`);
}

export function importJsonExport(date, payload, mode) {
  const query = mode ? `?mode=${encodeURIComponent(mode)}` : "";
  return request(`/exports/${date}.json${query}`, { method: "POST", body: JSON.stringify(payload) });
}

export async function getCsvExportText(date) {
  const response = await fetchWithTimeout(`${AI_API_BASE}/exports/${date}.csv`, { headers: { Accept: "text/csv" } }, 15000);
  if (!response.ok) throw new Error(`CSV 내보내기 실패 (${response.status})`);
  return response.text();
}

export function importCsvExport(date, csvText) {
  return request(`/exports/${date}.csv`, { method: "POST", body: JSON.stringify({ csv: csvText }) });
}
