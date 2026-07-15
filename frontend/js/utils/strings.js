export function parseKeywordList(text) { return [...new Set(text.split(/[,\n]/).map(v => v.trim()).filter(Boolean))]; }
export function cleanText(value) { const doc = new DOMParser().parseFromString(String(value || ""), "text/html"); return (doc.body.textContent || "").replace(/\s+/g, " ").trim(); }
export function safeUrl(value) { try { const u = new URL(String(value || "")); return ["http:", "https:"].includes(u.protocol) ? u.href : ""; } catch { return ""; } }
export function inferSourceFromTitle(title) { const match = title.match(/\s[-–—]\s([^-–—]{2,30})$/u); return match?.[1] || "출처 미상"; }
export function countBy(items, key) { return items.reduce((acc, item) => { const k = item[key] || "other"; acc[k] = (acc[k] || 0) + 1; return acc; }, {}); }
export function shortText(value, max = 100) { const text = cleanText(value); return text.length > max ? `${text.slice(0, max - 1)}…` : text; }
export function friendlyError(error) {
  if (error?.name === "AbortError") return "연결 시간이 초과됐습니다.";
  const message = cleanText(error?.message || String(error || "알 수 없는 오류"));
  if (/failed to fetch|networkerror|load failed/i.test(message)) return "브라우저에서 데이터 서버에 연결할 수 없습니다(CORS 또는 네트워크 오류).";
  return message;
}
export function escapeHtml(value) { return String(value ?? "").replace(/[&<>'"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c])); }
export function escapeAttr(value) { return escapeHtml(value).replace(/`/g, "&#96;"); }
