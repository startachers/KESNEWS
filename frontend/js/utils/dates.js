export function localDateKey(date = new Date()) {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 10);
}

export function parseDate(value) { const d = value ? new Date(value) : new Date(); return Number.isNaN(d.getTime()) ? new Date().toISOString() : d.toISOString(); }
export function parseGdeltDate(value) { if (/^\d{8}T\d{6}Z$/.test(value || "")) return parseDate(`${value.slice(0,4)}-${value.slice(4,6)}-${value.slice(6,8)}T${value.slice(9,11)}:${value.slice(11,13)}:${value.slice(13,15)}Z`); return parseDate(value); }
export function dateValue(value) { const n = new Date(value || 0).getTime(); return Number.isNaN(n) ? 0 : n; }
export function formatDateTime(value) { if (!value) return "일시 미상"; try { return new Intl.DateTimeFormat("ko-KR", { month:"2-digit", day:"2-digit", hour:"2-digit", minute:"2-digit", hour12:false }).format(new Date(value)); } catch { return "일시 미상"; } }
export function formatTime(value) { if (!value) return ""; return new Intl.DateTimeFormat("ko-KR", { hour:"2-digit", minute:"2-digit", hour12:false }).format(new Date(value)); }
export function formatRelative(value) { const diff = Date.now() - dateValue(value); if (diff < 0) return formatDateTime(value); const h = Math.floor(diff/3600000); return h < 1 ? "1시간 이내" : h < 24 ? `${h}시간 전` : `${Math.floor(h/24)}일 전`; }
