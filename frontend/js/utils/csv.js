export function parseCsv(text) {
  const rows = []; let row = [], cell = "", quoted = false;
  for (let i=0; i<text.length; i++) {
    const c = text[i];
    if (c === '"' && quoted && text[i+1] === '"') { cell += '"'; i++; }
    else if (c === '"') quoted = !quoted;
    else if (c === "," && !quoted) { row.push(cell); cell = ""; }
    else if ((c === "\n" || c === "\r") && !quoted) { if (c === "\r" && text[i+1] === "\n") i++; row.push(cell); if (row.some(v=>v.trim())) rows.push(row); row=[]; cell=""; }
    else cell += c;
  }
  row.push(cell); if (row.some(v=>v.trim())) rows.push(row);
  if (rows.length < 2) return [];
  const headers = rows.shift().map(h => h.replace(/^﻿/, "").trim());
  return rows.map(values => Object.fromEntries(headers.map((h,i) => [h, values[i] || ""])));
}
