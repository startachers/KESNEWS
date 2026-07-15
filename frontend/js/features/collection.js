import { state, settings, LAST_AUTO_KEY, setSearching, isSearching, saveDailyState } from "../state/store.js";
import { localDateKey, parseDate, parseGdeltDate, dateValue } from "../utils/dates.js";
import { cleanText, uid, shortText, friendlyError, safeUrl, inferSourceFromTitle } from "../utils/strings.js";
import { fetchWithTimeout } from "../utils/net.js";
import { showToast, setStatus, setSearchButton } from "../ui/notifications.js";
import { renderSidePanel, renderAll } from "../ui/renderers.js";
import { refreshRuleSummaryIfNeeded } from "./ai-analysis.js";

export async function runSearch(auto = false) {
  if (isSearching) return;
  if (state.date !== localDateKey() && auto) return;
  const enabled = settings.queries.filter(q => q.enabled && q.query.trim());
  if (!enabled.length && !settings.enableYonhap) { showToast("활성화된 검색식이나 뉴스 수집원이 없습니다. 설정을 확인해 주세요.", "error"); return; }
  setSearching(true);
  state.demo = false;
  setSearchButton(true);
  setStatus("busy", `연합뉴스 우선 · ${enabled.length}개 검색식으로 기사를 찾는 중…`);
  renderSidePanel();

  try {
    const tasks = [
      ...(settings.enableYonhap ? [{ label: "연합뉴스", category: "auto", fetcher: fetchYonhapRss }] : []),
      ...enabled.map(query => ({ label: query.label, category: query.id, fetcher: () => fetchQuery(query) }))
    ];
    const results = await Promise.allSettled(tasks.map(task => task.fetcher()));
    const collected = [];
    const providers = new Set();
    const failures = [];
    const warnings = [];
    results.forEach((result, index) => {
      const task = tasks[index];
      if (result.status === "fulfilled") {
        result.value.items.forEach(item => collected.push({ ...item, category: task.category === "auto" ? inferCategory(item) : task.category }));
        if (result.value.provider) providers.add(result.value.provider);
        if (result.value.warning) warnings.push(`${task.label}: ${result.value.warning}`);
      } else {
        failures.push(`${task.label}: ${friendlyError(result.reason)}`);
      }
    });

    let networkSucceeded = providers.size > 0;
    if (!collected.length && failures.length) {
      try {
        const gdeltItems = await fetchGdeltCombined();
        gdeltItems.forEach(item => collected.push({ ...item, category: inferCategory(item) }));
        providers.add("GDELT");
        networkSucceeded = true;
        warnings.push(...failures.map(message => `RSS 보조 전환: ${message}`));
        failures.length = 0;
      } catch (gdeltError) {
        failures.push(`GDELT 보조: ${friendlyError(gdeltError)}`);
      }
    }

    const eligible = collected
      .filter(a => !shouldExclude(a))
      .filter(a => withinLookback(a.pubDate, settings.lookback));
    const firstPass = deduplicateDetailed(eligible);
    const oldArticles = state.articles.filter(a => !a.isDemo);
    const fresh = firstPass.items
      .map(raw => {
        const classified = classifyArticle(raw);
        const old = oldArticles.find(article => sameArticle(article, classified));
        return { ...classified, included: old?.included ?? false, starred: old?.starred ?? false, note: old?.note || "" };
      })
      .sort(relevanceSort)
      .slice(0, Number(settings.collectionLimit || 200));

    state.lastAttemptAt = new Date().toISOString();
    if (networkSucceeded) {
      const manual = state.articles.filter(a => a.manual && !a.isDemo);
      const finalPass = deduplicateDetailed([...manual, ...fresh]);
      state.articles = finalPass.items.sort(relevanceSort);
      state.demo = false;
      state.fetchedAt = state.lastAttemptAt;
      state.lastRunStatus = "success";
      state.provider = [...providers].join(" + ");
      state.rawCollectedCount = collected.length;
      state.duplicatesRemoved = firstPass.removed + finalPass.removed;
      state.errors = [];
      state.warnings = [...warnings, ...failures.map(message => `일부 검색 실패: ${message}`)];
      localStorage.setItem(LAST_AUTO_KEY, localDateKey());
      state.summaryError = "";
      refreshRuleSummaryIfNeeded();

      if (fresh.length) {
        setStatus("live", `${fresh.length}건 정리 · 중복 ${state.duplicatesRemoved}건 제거`);
        showToast(`${fresh.length}건을 정리하고 중복 ${state.duplicatesRemoved}건을 제거했습니다.${state.warnings.length ? ` 일부 검색 ${state.warnings.length}건은 보조 처리했습니다.` : ""}`, state.warnings.length ? "" : "success");
      } else {
        setStatus("idle", "검색 기간 내 관련 기사가 없습니다");
        showToast("수집 연결은 정상이지만 검색 기간 내 관련 기사가 없습니다.");
      }
    } else {
      state.lastRunStatus = "error";
      state.provider = "수집 실패";
      state.errors = failures.length ? failures : ["데이터 제공 경로에서 응답을 받지 못했습니다."];
      state.warnings = warnings;
      localStorage.removeItem(LAST_AUTO_KEY);
      setStatus("error", "기사 수집 실패 · 오류 상세를 확인하세요");
      showToast(`수집 실패: ${shortText(state.errors[0], 120)}`, "error");
    }
    saveDailyState();
  } catch (error) {
    state.lastAttemptAt = new Date().toISOString();
    state.lastRunStatus = "error";
    state.errors = [friendlyError(error)];
    localStorage.removeItem(LAST_AUTO_KEY);
    saveDailyState();
    setStatus("error", "기사 검색을 완료하지 못했습니다");
    showToast(friendlyError(error), "error");
  } finally {
    setSearching(false);
    setSearchButton(false);
    renderAll();
  }
}

export async function fetchQuery(queryDef) {
  if (settings.endpoint.trim()) {
    try { return { items: await fetchCustomEndpoint(queryDef), provider: "기관용 뉴스 API" }; }
    catch (endpointError) {
      try {
        return { items: await fetchGoogleRss(queryDef), provider: "Google 뉴스 RSS", warning: `기관 API 연결 실패(${friendlyError(endpointError)})로 공개 RSS를 사용했습니다.` };
      } catch (rssError) {
        throw new Error(`기관 API: ${friendlyError(endpointError)} / RSS: ${friendlyError(rssError)}`);
      }
    }
  }
  return { items: await fetchGoogleRss(queryDef), provider: "Google 뉴스 RSS" };
}

export async function fetchGoogleRss(queryDef) {
  const days = Math.max(1, Math.ceil(Number(settings.lookback) / 24));
  const feedUrl = `https://news.google.com/rss/search?q=${encodeURIComponent(`${queryDef.query} when:${days}d`)}&hl=ko&gl=KR&ceid=KR:ko`;
  const proxy = settings.proxy.trim();
  if (!proxy) throw new Error("RSS 프록시 주소가 비어 있습니다.");
  const url = proxy.includes("{url}") ? proxy.replace("{url}", encodeURIComponent(feedUrl)) : proxy + encodeURIComponent(feedUrl);
  const response = await fetchWithTimeout(url, { headers: { Accept: "application/rss+xml, application/xml, text/xml, */*" } }, 16000);
  if (!response.ok) throw new Error(`프록시 응답 ${response.status}`);
  const text = await response.text();
  return parseRssItems(text, "Google 뉴스 RSS").slice(0, Number(settings.maxRecords)).map(item => {
    const source = item.source;
    let title = item.title;
    if (source && title.endsWith(` - ${source}`)) title = title.slice(0, -(source.length + 3)).trim();
    return { ...item, title, source: source || inferSourceFromTitle(title) };
  });
}

export async function fetchYonhapRss() {
  const feedUrl = "https://www.yna.co.kr/rss/news.xml";
  const proxy = settings.proxy.trim();
  if (!proxy) throw new Error("RSS 프록시 주소가 비어 있습니다.");
  const url = proxy.includes("{url}") ? proxy.replace("{url}", encodeURIComponent(feedUrl)) : proxy + encodeURIComponent(feedUrl);
  const response = await fetchWithTimeout(url, { headers: { Accept: "application/rss+xml, application/xml, text/xml, */*" } }, 16000);
  if (!response.ok) throw new Error(`연합뉴스 RSS 프록시 응답 ${response.status}`);
  const text = await response.text();
  const items = parseRssItems(text, "연합뉴스 RSS", "연합뉴스")
    .filter(item => withinLookback(item.pubDate, settings.lookback))
    .filter(item => getRelevance(item).rank < 99)
    .slice(0, Number(settings.collectionLimit || 200));
  return { items, provider: "연합뉴스 RSS" };
}

export function parseRssItems(text, provider, defaultSource = "") {
  const xml = new DOMParser().parseFromString(text, "text/xml");
  if (xml.querySelector("parsererror")) throw new Error("RSS 형식을 읽을 수 없습니다.");
  return [...xml.querySelectorAll("item")].map(item => {
    const source = cleanText(item.querySelector("source")?.textContent || "");
    const dateNode = item.querySelector("pubDate") || item.getElementsByTagName("dc:date")[0];
    return {
      id: uid(), title: cleanText(item.querySelector("title")?.textContent || "제목 없음"), source: source || defaultSource,
      url: cleanText(item.querySelector("link")?.textContent || ""),
      pubDate: parseDate(dateNode?.textContent),
      description: cleanText(item.querySelector("description")?.textContent || ""),
      provider
    };
  });
}

export async function fetchGdeltCombined() {
  const terms = settings.coreKeywords.filter(Boolean).map(term => `"${term.replaceAll('"', "")}"`).join(" OR ");
  const query = `(${terms}) sourcelang:korean`;
  const limit = Math.min(100, Math.max(20, Number(settings.maxRecords) * 3));
  const url = `https://api.gdeltproject.org/api/v2/doc/doc?query=${encodeURIComponent(query)}&mode=artlist&maxrecords=${limit}&format=json&timespan=${Number(settings.lookback)}h&sort=datedesc`;
  const response = await fetchWithTimeout(url, { headers: { Accept: "application/json" } }, 18000);
  const text = await response.text();
  if (!response.ok) {
    const detail = shortText(cleanText(text), 140);
    throw new Error(response.status === 429 ? `GDELT 속도 제한(429): ${detail || "잠시 후 다시 시도해 주세요."}` : `GDELT 응답 ${response.status}: ${detail}`);
  }
  let data;
  try { data = JSON.parse(text); }
  catch { throw new Error(`GDELT 응답 형식 오류: ${shortText(cleanText(text), 140)}`); }
  return (data.articles || []).map(item => ({
    id: uid(), title: cleanText(item.title || "제목 없음"), source: cleanText(item.domain || "출처 미상"),
    url: item.url || "", pubDate: parseGdeltDate(item.seendate), description: cleanText(item.socialimage ? "" : (item.snippet || "")), provider: "GDELT"
  }));
}

export function inferCategory(article) {
  const text = `${article.title || ""} ${article.description || ""}`.toLowerCase();
  const rules = [
    ["safety", ["화재", "감전", "사고", "안전점검", "누전", "정전", "재해"]],
    ["management", ["사장", "감사", "국정감사", "경영평가", "인사", "채용", "노조", "비위"]],
    ["policy", ["산업통상", "전기안전관리법", "정책", "규제", "법안", "국회"]],
    ["industry", ["태양광", "ess", "전기차", "배터리", "신재생", "충전시설"]],
    ["community", ["협약", "봉사", "지원", "캠페인", "지역", "상생"]]
  ];
  return rules.find(([, keywords]) => keywords.some(keyword => text.includes(keyword)))?.[0] || "direct";
}

export async function fetchCustomEndpoint(queryDef) {
  const endpoint = settings.endpoint.trim()
    .replaceAll("{query}", encodeURIComponent(queryDef.query))
    .replaceAll("{hours}", encodeURIComponent(settings.lookback))
    .replaceAll("{limit}", encodeURIComponent(settings.maxRecords));
  const response = await fetchWithTimeout(endpoint, { headers: { Accept: "application/json" } }, 16000);
  if (!response.ok) throw new Error(`기관 API 응답 ${response.status}`);
  const data = await response.json();
  const items = Array.isArray(data) ? data : (data.items || data.articles || []);
  return items.slice(0, Number(settings.maxRecords)).map(item => ({
    id: uid(),
    title: cleanText(item.title || item.headline || "제목 없음"),
    source: cleanText(item.source?.name || item.source || item.publisher || item.domain || "출처 미상"),
    url: item.originallink || item.url || item.link || "",
    pubDate: parseDate(item.pubDate || item.publishedAt || item.seendate || item.date),
    description: cleanText(item.description || item.summary || item.snippet || ""),
    provider: "기관용 뉴스 API"
  }));
}

export function classifyArticle(raw) {
  const text = `${raw.title} ${raw.description || ""}`.toLowerCase();
  const title = raw.title.toLowerCase();
  let score = 0;
  const matched = [];
  const heavy = { "사망": 6, "중대재해": 6, "압수수색": 6, "고발": 5, "해킹": 5, "감전": 4, "화재": 4, "사고": 3, "논란": 3, "위반": 3, "부실": 3, "정전": 3, "피해": 3, "국정감사": 2, "감사": 2, "징계": 4 };
  settings.riskKeywords.forEach(k => {
    const key = k.trim(); if (!key || !text.includes(key.toLowerCase())) return;
    matched.push(key); score += heavy[key] || 2; if (title.includes(key.toLowerCase())) score += 1;
  });
  const positives = settings.positiveKeywords.filter(k => k.trim() && text.includes(k.trim().toLowerCase()));
  positives.forEach(k => { if (!matched.includes(k)) matched.push(k); });
  const risk = score >= 6 ? "critical" : score >= 3 ? "watch" : "routine";
  const sentiment = score >= 3 ? "negative" : positives.length ? "positive" : "neutral";
  return { ...raw, id: raw.id || uid(), pubDate: raw.pubDate || new Date().toISOString(), description: cleanText(raw.description || ""), matchedKeywords: matched.slice(0,8), risk, riskScore: score, sentiment, included: raw.included ?? !!raw.manual, starred: !!raw.starred, note: raw.note || "", manual: !!raw.manual, isDemo: !!raw.isDemo };
}

export function shouldExclude(article) {
  const text = `${article.title} ${article.description || ""}`.toLowerCase();
  return settings.excludeKeywords.some(k => k.trim() && text.includes(k.trim().toLowerCase()));
}

export function deduplicate(items) {
  return deduplicateDetailed(items).items;
}

export function deduplicateDetailed(items) {
  const unique = [];
  let removed = 0;
  items.forEach(item => {
    const classified = item.risk ? item : classifyArticle(item);
    const index = unique.findIndex(existing => sameArticle(existing, classified));
    if (index < 0) unique.push(classified);
    else {
      unique[index] = mergeDuplicateArticles(unique[index], classified);
      removed += 1;
    }
  });
  return { items: unique, removed };
}

export function sameArticle(a, b) {
  const leftUrl = canonicalArticleUrl(a.url);
  const rightUrl = canonicalArticleUrl(b.url);
  if (leftUrl && rightUrl && leftUrl === rightUrl) return true;
  const leftTitle = normalizedArticleTitle(a.title);
  const rightTitle = normalizedArticleTitle(b.title);
  if (!leftTitle || !rightTitle) return false;
  if (leftTitle === rightTitle) return true;
  if (Math.min(leftTitle.length, rightTitle.length) < 16) return false;
  const leftDate = dateValue(a.pubDate);
  const rightDate = dateValue(b.pubDate);
  if (leftDate && rightDate && Math.abs(leftDate - rightDate) > 72 * 3600000) return false;
  return bigramSimilarity(leftTitle, rightTitle) >= 0.9;
}

export function mergeDuplicateArticles(left, right) {
  const preference = articlePreference(right) > articlePreference(left) ? right : left;
  const other = preference === left ? right : left;
  const longerDescription = (left.description || "").length >= (right.description || "").length ? left.description : right.description;
  return {
    ...other,
    ...preference,
    description: longerDescription || preference.description || "",
    included: !!(left.included || right.included),
    starred: !!(left.starred || right.starred),
    note: left.note || right.note || "",
    matchedKeywords: [...new Set([...(left.matchedKeywords || []), ...(right.matchedKeywords || [])])].slice(0, 8),
    duplicateSources: [...new Set([...(left.duplicateSources || []), ...(right.duplicateSources || []), left.source, right.source].filter(Boolean))]
  };
}

export function articlePreference(article) {
  return (article.manual ? 1000 : 0) + (isYonhapArticle(article) ? 500 : 0) + Math.min((article.description || "").length, 300) + dateValue(article.pubDate) / 1e13;
}

export function normalizedArticleTitle(value) {
  return cleanText(value || "").normalize("NFKC").toLowerCase()
    .replace(/^\s*[\[【(][^\]】)]{1,18}[\]】)]\s*/u, "")
    .replace(/\s*[-–—]\s*[^-–—]{2,24}$/u, "")
    .replace(/[^가-힣a-z0-9]/g, "")
    .slice(0, 180);
}

export function canonicalArticleUrl(value) {
  const safe = safeUrl(value);
  if (!safe) return "";
  try {
    const url = new URL(safe);
    if (url.hostname.includes("news.google.com")) return "";
    url.hash = "";
    ["utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "ref", "source"].forEach(key => url.searchParams.delete(key));
    return `${url.hostname.replace(/^www\./, "")}${url.pathname.replace(/\/$/, "")}${url.search}`.toLowerCase();
  } catch { return ""; }
}

export function bigramSimilarity(left, right) {
  const grams = value => {
    const result = new Map();
    for (let index = 0; index < value.length - 1; index += 1) {
      const gram = value.slice(index, index + 2);
      result.set(gram, (result.get(gram) || 0) + 1);
    }
    return result;
  };
  const a = grams(left);
  const b = grams(right);
  let overlap = 0;
  a.forEach((count, gram) => { overlap += Math.min(count, b.get(gram) || 0); });
  return (2 * overlap) / Math.max(1, left.length + right.length - 2);
}

export function isYonhapArticle(article) {
  if ((article.source || "").trim() === "연합뉴스" || (article.provider || "").trim() === "연합뉴스") return true;
  try {
    const hostname = new URL(article.url || "").hostname.toLowerCase();
    return hostname === "yna.co.kr" || hostname.endsWith(".yna.co.kr");
  }
  catch { return false; }
}

export function articleKey(a) {
  return normalizedArticleTitle(a.title) || canonicalArticleUrl(a.url) || a.id;
}

export function withinLookback(date, hours) {
  const value = dateValue(date);
  if (!value) return true;
  const targetDate = state.date === localDateKey() ? Date.now() : new Date(`${state.date}T23:59:59`).getTime();
  return value <= targetDate + 3600000 && value >= targetDate - Number(hours) * 3600000;
}

export function getRelevance(article) {
  const normalize = value => cleanText(value || "").normalize("NFKC").toLowerCase().replace(/\s+/g, " ");
  const title = normalize(article.title);
  const fullText = `${title} ${normalize(article.description)}`;
  const criteria = [
    { rank: 1, reason: "① 공사 직접 거론", match: text => /한국전기안전공사|전기안전공사/u.test(text) },
    { rank: 2, reason: "② 전기화재", match: text => /전기[\s·ㆍ-]*화재/u.test(text) },
    { rank: 3, reason: "③ 감전사고", match: text => /감전[\s·ㆍ-]*사고/u.test(text) },
    { rank: 4, reason: "④ 기후에너지환경부+에너지/전기", match: text => {
      if (!text.includes("기후에너지환경부")) return false;
      const context = text.replaceAll("기후에너지환경부", " ");
      return /에너지|전기/u.test(context);
    } },
    { rank: 5, reason: "⑤ 재생에너지", match: text => /재생[\s·ㆍ-]*에너지/u.test(text) }
  ];
  const matches = criteria.filter(criterion => criterion.match(fullText));
  if (!matches.length) return { rank: 99, score: 0, label: "낮음", titleMatch: false, matchCount: 0, reasons: ["지정 관련도 기준 미일치"] };
  const primary = matches[0];
  const titleMatch = primary.match(title);
  const baseScore = { 1: 100, 2: 85, 3: 70, 4: 55, 5: 40 }[primary.rank];
  const score = primary.rank === 1 ? 100 : Math.min(99, baseScore + (titleMatch ? 7 : 0) + Math.min(5, (matches.length - 1) * 2));
  const label = primary.rank === 1 ? "매우 높음" : primary.rank <= 3 ? "높음" : primary.rank === 4 ? "보통" : "관심";
  return { rank: primary.rank, score, label, titleMatch, matchCount: matches.length, reasons: matches.map(match => match.reason) };
}

export function relevanceSort(a, b) {
  const left = getRelevance(a);
  const right = getRelevance(b);
  const riskOrder = { critical: 3, watch: 2, routine: 1 };
  return left.rank - right.rank
    || Number(isYonhapArticle(b)) - Number(isYonhapArticle(a))
    || Number(b.starred) - Number(a.starred)
    || Number(right.titleMatch) - Number(left.titleMatch)
    || right.matchCount - left.matchCount
    || right.score - left.score
    || (riskOrder[b.risk] || 0) - (riskOrder[a.risk] || 0)
    || dateValue(b.pubDate) - dateValue(a.pubDate)
    || (a.title || "").localeCompare(b.title || "", "ko")
    || String(a.id || "").localeCompare(String(b.id || ""));
}

export function prioritySort(a, b) {
  const score = x => (x.starred ? 1000 : 0) + (x.risk === "critical" ? 300 : x.risk === "watch" ? 150 : 0) + Math.min((x.riskScore || 0) * 8, 80) + (x.sentiment === "positive" ? 8 : 0) + dateValue(x.pubDate) / 1e13;
  return score(b) - score(a);
}
