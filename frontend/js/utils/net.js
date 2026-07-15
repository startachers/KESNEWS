export function fetchWithTimeout(url, options = {}, ms = 15000) {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), ms);
  const signals = [controller.signal, options.signal].filter(Boolean);
  const signal = signals.length > 1 && typeof AbortSignal.any === "function" ? AbortSignal.any(signals) : controller.signal;
  return fetch(url, { ...options, signal, cache: "no-store" }).finally(() => clearTimeout(timer));
}
