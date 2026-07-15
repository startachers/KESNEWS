import { AI_API_BASE } from "../state/store.js";
import { fetchWithTimeout } from "../utils/net.js";

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

export function putBriefing(date, expectedRevision, patch) {
  return request(`/briefings/${date}`, { method: "PUT", body: JSON.stringify({ expectedRevision, patch }) });
}

export function analyzeBriefing(date, expectedRevision, model, signal) {
  return request(`/briefings/${date}/analyze`, {
    method: "POST",
    body: JSON.stringify({ expectedRevision, model }),
    signal,
  }, 600000);
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
  return request(`/collections`, { method: "POST", body: JSON.stringify(payload) }, 45000);
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
