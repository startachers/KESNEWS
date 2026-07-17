import { els, state } from "../state/store.js";
import * as api from "../api/client.js";
import { escapeHtml, friendlyError } from "../utils/strings.js";
import { formatDateTime, localDateKey } from "../utils/dates.js";
import { showToast } from "../ui/notifications.js?v=20260716-1";

const LEVEL_LABELS = { critical: "긴급", watch: "주의", info: "참고", normal: "정상", unknown: "확인 불가" };
const HAZARD_LABELS = { heavy_rain: "호우", typhoon: "태풍", heat: "폭염", strong_wind: "강풍", snow: "대설", cold: "한파", dry: "건조", other: "위험기상" };
const REGION_LABELS = { capital: "수도권", gangwon: "강원권", chungcheong: "충청권", honam: "호남권", yeongnam: "영남권", jeju: "제주권", national: "전국" };

function contextForDisplay() {
  return state.weather?.latestContext || state.weather?.attachedContext || null;
}

function temperatureLabel(day) {
  const low = day.temperature?.min;
  const high = day.temperature?.max;
  return low == null || high == null ? "기온 정보 없음" : `${low}~${high}℃`;
}

function compactLevelLabel(level) {
  return { critical: "위험 감지", watch: "주의 필요", normal: "특이사항 없음", unknown: "확인 필요" }[level] || "확인 필요";
}

function compactAlertLabel(context) {
  const signals = context.riskSignals || [];
  if (!signals.length) {
    return context.sourceStatus?.alerts?.status === "success" ? "현재 발효 중인 주요 특보 없음" : "특보 현재상태 확인 필요";
  }
  const groups = new Map();
  signals.forEach(signal => {
    const preliminary = (signal.evidence || []).some(item => String(item.title || "").includes("예비특보"));
    const label = `${HAZARD_LABELS[signal.hazard] || signal.hazard} ${preliminary ? "예비" : LEVEL_LABELS[signal.level] || signal.level}`;
    const group = groups.get(label) || { count: 0, regions: new Set() };
    group.count += 1;
    (signal.regionIds || []).forEach(region => group.regions.add(region));
    groups.set(label, group);
  });
  return [...groups].slice(0, 4).map(([label, group]) => {
    const regions = [...group.regions].map(id => REGION_LABELS[id] || id);
    const regionLabel = regions.length > 3 ? `${regions.slice(0, 3).join("·")} 외 ${regions.length - 3}권역` : regions.join("·");
    return `${label} ${group.count}건${regionLabel ? ` (${regionLabel})` : ""}`;
  }).join(" · ");
}

function compactFocusLabel(context) {
  const signals = [...(context.riskSignals || [])].sort((a, b) => {
    const priority = { critical: 0, watch: 1, info: 2, normal: 3, unknown: 4 };
    return (priority[a.level] ?? 9) - (priority[b.level] ?? 9);
  });
  if (!signals.length) return "별도 우선 확인 지역 없음";
  const highestLevel = signals[0].level;
  return signals.filter(signal => signal.level === highestLevel).slice(0, 2).map(signal => {
    const title = signal.evidence?.[0]?.title || "";
    const area = title.includes(":") ? title.split(":").slice(1).join(":").trim() : "";
    const conciseArea = area.length > 72 ? `${area.slice(0, 72).trim()}…` : area;
    const fallback = (signal.regionIds || []).map(id => REGION_LABELS[id] || id).join("·") || "전국";
    return `${HAZARD_LABELS[signal.hazard] || signal.hazard} ${LEVEL_LABELS[signal.level] || signal.level} — ${conciseArea || fallback}`;
  }).join(" / ");
}

function compactForecastLabel(context) {
  const days = context.days || [];
  if (!days.length) return "주요 예보를 확인할 수 없습니다.";
  const notable = days.filter(day => /비|눈|태풍|소나기|폭염|더위|한파/.test(day.weatherText || ""));
  const focus = (notable.length ? notable : days.slice(0, 2)).slice(0, 3);
  const summary = focus.map(day => `${day.date.slice(5)} ${day.weatherText || "정보 없음"}`).join(" · ");
  return summary;
}

function compactTemperatureLabel(context) {
  const lows = (context.days || []).map(day => day.temperature?.min).filter(value => value != null);
  const highs = (context.days || []).map(day => day.temperature?.max).filter(value => value != null);
  return lows.length && highs.length ? `${Math.min(...lows)}~${Math.max(...highs)}℃` : "정보 없음";
}

function maxHourlyPrecipitationDay(context) {
  const candidates = (context.days || []).filter(day => day.maxHourlyPrecipitation);
  if (!candidates.length) return null;
  return candidates.reduce((selected, item) => {
    const amount = item.maxHourlyPrecipitation;
    const selectedAmount = selected.maxHourlyPrecipitation;
    const score = amount.max == null ? amount.min + 10000 : amount.max;
    const selectedScore = selectedAmount.max == null ? selectedAmount.min + 10000 : selectedAmount.max;
    return score > selectedScore ? item : selected;
  });
}

function compactRainfallLabel(context) {
  const day = maxHourlyPrecipitationDay(context);
  if (!day) {
    const rainExpected = (context.days || []).slice(0, 4).some(day => /비|소나기|태풍/.test(day.weatherText || ""));
    return rainExpected ? "상세 수집 필요" : "강수 없음";
  }
  const rawAmount = day.maxHourlyPrecipitation.text;
  const amount = /mm$/i.test(rawAmount) ? rawAmount.replace(/mm$/i, "mm/h") : `${rawAmount}mm/h`;
  return `${day.date.slice(5)} ${amount}`;
}

function compactProbabilityLabel(context) {
  const candidates = (context.days || []).filter(day => day.maxPrecipitationProbability != null);
  if (!candidates.length) return "정보 없음";
  const day = candidates.reduce((selected, item) => item.maxPrecipitationProbability > selected.maxPrecipitationProbability ? item : selected);
  return `${day.date.slice(5)} ${day.maxPrecipitationProbability}%`;
}

function setMetricEmphasis(element, value, cautionAt, highAt) {
  element.closest("span").dataset.emphasis = value >= highAt ? "high" : value >= cautionAt ? "caution" : "normal";
}

function rainfallText(amount) {
  if (!amount?.text) return "강수량 정보 없음";
  return /mm$/i.test(amount.text) ? amount.text.replace(/mm$/i, "mm/h") : `${amount.text}mm/h`;
}

function rainfallScore(amount) {
  return amount ? (amount.max ?? amount.min + 10000) : 0;
}

function metricImportance({ rainfall = 0, probability = 0, temperature = -Infinity } = {}) {
  if (rainfall >= 30 || temperature >= 35) return "high";
  if (rainfall >= 10 || probability >= 60 || temperature >= 33) return "caution";
  return "normal";
}

function metricBadge({ rainfall = 0, probability = 0, temperature = -Infinity } = {}) {
  if (rainfall >= 30) return "집중호우";
  if (temperature >= 35) return "폭염";
  if (rainfall >= 10) return "강한 비";
  if (probability >= 80) return "강수확률 높음";
  if (temperature >= 33) return "고온";
  return "";
}

function highestRegionalValue(context, selector, score) {
  const candidates = (context.days || []).flatMap(day => (day.regions || []).map(region => ({ day, region, value: selector(region) }))).filter(item => item.value != null);
  return candidates.reduce((selected, item) => !selected || score(item.value) > score(selected.value) ? item : selected, null);
}

function renderWeatherDetails(context, visibleSignals, regionId) {
  const rainfall = highestRegionalValue(context, region => region.maxHourlyPrecipitation, amount => amount.max ?? amount.min + 10000);
  const temperature = highestRegionalValue(context, region => region.temperature?.max, value => value);
  const alerts = (context.alerts || []).filter(alert => regionId === "national" || (alert.regionIds || []).includes(regionId) || (alert.regionIds || []).includes("national"));
  const currentAlerts = alerts.filter(alert => !alert.preliminary);
  const preliminaryAlerts = alerts.filter(alert => alert.preliminary);
  const priority = [...visibleSignals].sort((a, b) => ({ critical: 0, watch: 1, info: 2, normal: 3 }[a.level] ?? 9) - ({ critical: 0, watch: 1, info: 2, normal: 3 }[b.level] ?? 9))[0];

  els.weatherDetailRainfall.textContent = rainfall ? rainfallText(rainfall.value) : "정보 없음";
  els.weatherDetailRainfallPlace.textContent = rainfall ? `${rainfall.day.date.slice(5)} · ${rainfall.region.regionLabel || REGION_LABELS[rainfall.region.regionId] || rainfall.region.regionId}` : "단기예보 제공값 없음";
  els.weatherDetailTemperature.textContent = temperature ? `${temperature.value}℃` : "정보 없음";
  els.weatherDetailTemperaturePlace.textContent = temperature ? `${temperature.day.date.slice(5)} · ${temperature.region.regionLabel || REGION_LABELS[temperature.region.regionId] || temperature.region.regionId}` : "기온예보 제공값 없음";
  els.weatherDetailAlertSummary.textContent = `현재 ${currentAlerts.length}건 · 예비 ${preliminaryAlerts.length}건`;
  if (priority) {
    const title = priority.evidence?.[0]?.title || "";
    const area = title.includes(":") ? title.split(":").slice(1).join(":").trim() : (priority.regionIds || []).map(id => REGION_LABELS[id] || id).join("·");
    els.weatherDetailPriority.textContent = `${HAZARD_LABELS[priority.hazard] || priority.hazard} ${LEVEL_LABELS[priority.level] || priority.level} · ${area}`;
  } else {
    els.weatherDetailPriority.textContent = "별도 위험 신호 없음";
  }
  const rainfallAmount = rainfall ? rainfallScore(rainfall.value) : 0;
  const alertImportance = visibleSignals.some(signal => signal.level === "critical") ? "high" : visibleSignals.some(signal => signal.level === "watch") ? "caution" : "normal";
  els.weatherDetailRainfall.closest("article").dataset.emphasis = metricImportance({ rainfall: rainfallAmount });
  els.weatherDetailTemperature.closest("article").dataset.emphasis = metricImportance({ temperature: temperature?.value });
  els.weatherDetailAlertSummary.closest("article").dataset.emphasis = alertImportance;
  els.weatherDetailPriority.closest("article").dataset.emphasis = alertImportance;

  const sourceLabels = { alerts: "기상특보", shortForecast: "단기예보 D0~D3", midForecast: "중기예보 D4~D6" };
  els.weatherSourceGrid.innerHTML = Object.entries(context.sourceStatus || {}).map(([name, item]) => `<article class="weather-source-item status-${escapeHtml(item.status || "unknown")}"><span>${escapeHtml(sourceLabels[name] || name)}</span><strong>${escapeHtml(item.status === "success" ? "정상" : item.status || "확인 불가")}</strong><small>${escapeHtml(item.issuedAt ? `${formatDateTime(item.issuedAt)} 발표` : "발표시각 확인 불가")}</small>${item.error ? `<p>${escapeHtml(item.error)}</p>` : ""}</article>`).join("");

  els.weatherOfficialAlerts.innerHTML = alerts.map((alert, index) => {
    const regions = (alert.regionIds || []).map(id => REGION_LABELS[id] || id).join(" · ");
    return `<article class="weather-official-alert ${alert.preliminary ? "preliminary" : "current"}"><div><span>${alert.preliminary ? "예비특보" : "현재특보"}</span><strong>${String(index + 1).padStart(2, "0")}</strong></div><section><h4>${escapeHtml(alert.title || "기상특보")}</h4><p><b>영향 권역</b> ${escapeHtml(regions || "전국")}</p><small>발표 ${escapeHtml(alert.issuedAt ? formatDateTime(alert.issuedAt) : "시각 미상")} · 발효 ${escapeHtml(alert.effectiveAt ? formatDateTime(alert.effectiveAt) : "시각 미상")}</small></section></article>`;
  }).join("") || '<p class="weather-empty">선택 권역에 발효된 공식 특보가 없습니다.</p>';

  const rainfallDay = maxHourlyPrecipitationDay(context);
  const defaultDate = rainfallDay?.date || context.days?.[0]?.date || "";
  const comparisonDate = (context.days || []).some(day => day.date === state.weatherComparisonDate) ? state.weatherComparisonDate : defaultDate;
  els.weatherComparisonDaySelect.innerHTML = (context.days || []).map(day => `<option value="${escapeHtml(day.date)}" ${day.date === comparisonDate ? "selected" : ""}>${escapeHtml(day.date.slice(5))} ${escapeHtml(day.weatherText || "")}</option>`).join("");
  const comparisonDay = (context.days || []).find(day => day.date === comparisonDate);
  const comparisonRegions = comparisonDay?.regions || [];
  const maxima = {
    temperature: Math.max(...comparisonRegions.map(region => region.temperature?.max).filter(value => value != null), -Infinity),
    probability: Math.max(...comparisonRegions.map(region => region.maxPrecipitationProbability).filter(value => value != null), -Infinity),
    rainfall: Math.max(...comparisonRegions.map(region => rainfallScore(region.maxHourlyPrecipitation)), -Infinity),
    wind: Math.max(...comparisonRegions.map(region => region.maxWindSpeed).filter(value => value != null), -Infinity),
  };
  els.weatherRegionComparison.innerHTML = comparisonRegions.map(region => {
    const values = { rainfall: rainfallScore(region.maxHourlyPrecipitation), probability: region.maxPrecipitationProbability || 0, temperature: region.temperature?.max };
    const importance = metricImportance({ rainfall: values.rainfall, temperature: values.temperature });
    const badge = metricBadge(values);
    const peak = value => value != null && value !== -Infinity ? " metric-peak" : "";
    return `<article data-emphasis="${importance}"><header><strong>${escapeHtml(region.regionLabel || REGION_LABELS[region.regionId] || region.regionId)}</strong><span>${escapeHtml(region.weatherText || "정보 없음")}</span>${badge ? `<em>${escapeHtml(badge)}</em>` : ""}</header><dl><div class="${region.temperature?.max === maxima.temperature ? peak(region.temperature?.max) : ""}"><dt>최저·최고</dt><dd>${escapeHtml(temperatureLabel(region))}</dd></div><div class="${region.maxPrecipitationProbability === maxima.probability ? peak(region.maxPrecipitationProbability) : ""}"><dt>강수확률</dt><dd>${region.maxPrecipitationProbability == null ? "정보 없음" : `${escapeHtml(region.maxPrecipitationProbability)}%`}</dd></div><div class="${values.rainfall > 0 && values.rainfall === maxima.rainfall ? peak(values.rainfall) : ""}"><dt>시간강수량</dt><dd>${escapeHtml(rainfallText(region.maxHourlyPrecipitation))}</dd></div><div class="${region.maxWindSpeed === maxima.wind ? peak(region.maxWindSpeed) : ""}"><dt>최대풍속</dt><dd>${region.maxWindSpeed == null ? "정보 없음" : `${escapeHtml(region.maxWindSpeed)}m/s`}</dd></div></dl></article>`;
  }).join("") || '<p class="weather-empty">선택 날짜의 권역별 상세 예보가 없습니다.</p>';
}

export function renderWeather() {
  if (!els.weatherPanel) return;
  const weather = state.weather || {};
  const context = contextForDisplay();
  const finalized = state.status === "final";
  els.weatherPanel.dataset.level = context?.overallLevel || "unknown";
  els.weatherDetailPanel.dataset.level = context?.overallLevel || "unknown";
  els.weatherRefreshBtn.disabled = finalized || state.weatherLoading || state.date !== localDateKey();
  els.weatherReviewBtn.disabled = finalized || state.weatherLoading || !weather.latestContext;
  els.weatherRefreshBtn.textContent = state.weatherLoading ? "기상정보 수집 중…" : "기상정보 새로고침";

  if (!context) {
    els.weatherExcludeBtn.hidden = true;
    els.weatherLevel.textContent = weather.configured ? "수집 전" : "설정 필요";
    els.weatherAlertCount.textContent = "특보 현재상태 확인 불가";
    els.weatherDays.innerHTML = "";
    els.weatherRiskList.innerHTML = "";
    els.weatherSourceGrid.innerHTML = "";
    els.weatherOfficialAlerts.innerHTML = "";
    els.weatherComparisonDaySelect.innerHTML = "";
    els.weatherRegionComparison.innerHTML = "";
    els.weatherDetailRainfall.textContent = "정보 없음";
    els.weatherDetailRainfallPlace.textContent = "";
    els.weatherDetailTemperature.textContent = "정보 없음";
    els.weatherDetailTemperaturePlace.textContent = "";
    els.weatherDetailAlertSummary.textContent = "확인 불가";
    els.weatherDetailPriority.textContent = "확인 불가";
    els.weatherResponseTabCount.textContent = "0";
    els.weatherResponseTabCount.closest("button").dataset.emphasis = "normal";
    [els.weatherDetailRainfall, els.weatherDetailTemperature, els.weatherDetailAlertSummary, els.weatherDetailPriority].forEach(element => {
      element.closest("article").dataset.emphasis = "normal";
    });
    els.weatherSourceMeta.textContent = weather.configured
      ? "기상청 서비스는 설정됐지만 저장된 기상정보가 없습니다."
      : ".env에 KMA_SERVICE_KEY를 설정하면 기상청 예보·특보를 사용할 수 있습니다.";
    els.weatherStatus.className = "weather-status warning";
    els.weatherStatus.textContent = weather.configured ? "기상정보 새로고침을 실행해 주세요." : "기상청 서비스키가 설정되지 않았습니다. 기존 언론브리핑 기능은 계속 사용할 수 있습니다.";
    els.weatherReviewBtn.textContent = "CEO 보고 반영 검토";
    els.weatherCompactLevel.textContent = weather.configured ? "수집 전" : "설정 필요";
    els.weatherCompactAlerts.textContent = "특보 현재상태 확인 필요";
    els.weatherCompactFocus.textContent = "특보 지역 확인 필요";
    els.weatherCompactForecast.textContent = weather.configured ? "기상정보 새로고침이 필요합니다." : "기상청 서비스키 설정이 필요합니다.";
    els.weatherCompactTemperature.textContent = "정보 없음";
    els.weatherCompactRainfall.textContent = "정보 없음";
    els.weatherCompactProbability.textContent = "정보 없음";
    [els.weatherCompactTemperature, els.weatherCompactRainfall, els.weatherCompactProbability].forEach(element => {
      element.closest("span").dataset.emphasis = "normal";
    });
    els.weatherCompactSource.textContent = weather.configured ? "저장된 기상정보가 없습니다." : "기상청 예보·특보를 아직 사용할 수 없습니다.";
    els.weatherCompactNotice.textContent = "상세 기상정보에서 연결 상태를 확인할 수 있습니다.";
    return;
  }

  const regionId = state.weatherRegionId || "national";
  els.weatherRegionSelect.value = regionId;
  const visibleSignals = (context.riskSignals || []).filter(signal =>
    regionId === "national" || (signal.regionIds || []).includes(regionId) || (signal.regionIds || []).includes("national")
  );
  const alertStatus = context.sourceStatus?.alerts?.status;
  const level = visibleSignals.some(signal => signal.level === "critical")
    ? "critical"
    : visibleSignals.some(signal => signal.level === "watch")
      ? "watch"
      : alertStatus === "success" ? "normal" : "unknown";
  els.weatherDetailPanel.dataset.level = level;
  els.weatherResponseTabCount.textContent = String(visibleSignals.length);
  els.weatherResponseTabCount.closest("button").dataset.emphasis = level === "critical" ? "high" : level === "watch" ? "caution" : "normal";
  const sourceWarnings = Object.entries(context.sourceStatus || {}).filter(([, item]) => item.status !== "success");
  const selectedAttachment = weather.attached?.contextId === context.id && weather.attached?.includeInReport;
  const reviewed = selectedAttachment && weather.attached?.reviewStatus === "reviewed";
  const attachedSignals = new Map(
    (weather.attached?.contextId === context.id ? weather.attached?.signals || [] : []).map(item => [item.id, item])
  );
  els.weatherExcludeBtn.hidden = !reviewed;
  els.weatherExcludeBtn.disabled = finalized || state.weatherLoading;
  els.weatherLevelLabel.textContent = `${REGION_LABELS[regionId] || regionId} 위험도`;
  els.weatherLevel.textContent = LEVEL_LABELS[level] || level;
  els.weatherAlertCount.textContent = visibleSignals.length
    ? `전기재해 위험 신호 ${visibleSignals.length}건`
    : level === "unknown" ? "특보 현재상태 확인 불가" : "현재 위험 신호 없음";
  els.weatherSourceMeta.textContent = `기상청 ${context.issuedAt ? formatDateTime(context.issuedAt) : "발표시각 미상"} 발표 · ${formatDateTime(context.builtAt)} 수집`;
  els.weatherCompactLevel.textContent = compactLevelLabel(context.overallLevel || "unknown");
  els.weatherCompactAlerts.textContent = compactAlertLabel(context);
  els.weatherCompactFocus.textContent = compactFocusLabel(context);
  els.weatherCompactForecast.textContent = compactForecastLabel(context);
  els.weatherCompactTemperature.textContent = compactTemperatureLabel(context);
  els.weatherCompactRainfall.textContent = compactRainfallLabel(context);
  els.weatherCompactProbability.textContent = compactProbabilityLabel(context);
  const maximumTemperature = Math.max(...(context.days || []).map(day => day.temperature?.max).filter(value => value != null), -Infinity);
  const rainfallDay = maxHourlyPrecipitationDay(context);
  const rainfallAmount = rainfallDay ? (rainfallDay.maxHourlyPrecipitation.max ?? rainfallDay.maxHourlyPrecipitation.min + 10000) : 0;
  const maximumProbability = Math.max(...(context.days || []).map(day => day.maxPrecipitationProbability).filter(value => value != null), 0);
  setMetricEmphasis(els.weatherCompactTemperature, maximumTemperature, 33, 35);
  setMetricEmphasis(els.weatherCompactRainfall, rainfallAmount, 10, 30);
  setMetricEmphasis(els.weatherCompactProbability, maximumProbability, 60, 80);
  els.weatherCompactSource.textContent = `기상청 ${context.issuedAt ? formatDateTime(context.issuedAt) : "발표시각 미상"} 발표 · 상세 화면에서 검토·보고 반영`;
  els.weatherDays.innerHTML = (context.days || []).map(day => {
    const summary = regionId === "national"
      ? day
      : (day.regions || []).find(item => item.regionId === regionId) || day;
    const daySignals = visibleSignals.filter(signal => String(signal.startsAt || "").slice(0, 10) === day.date);
    const dayLevel = daySignals.some(signal => signal.level === "critical") ? "critical" : daySignals.some(signal => signal.level === "watch") ? "watch" : summary.riskLevel || "normal";
    const metrics = { rainfall: rainfallScore(summary.maxHourlyPrecipitation), probability: summary.maxPrecipitationProbability || 0, temperature: summary.temperature?.max };
    const importance = dayLevel === "critical" ? "high" : metricImportance(metrics);
    const badge = dayLevel === "critical" ? "공식 경보" : metricBadge(metrics);
    const pop = summary.maxPrecipitationProbability == null ? "" : ` · 강수 ${summary.maxPrecipitationProbability}%`;
    const rain = summary.maxHourlyPrecipitation?.text;
    const rainfall = rain ? `<small class="weather-day-rain">시간당 최대 ${escapeHtml(/mm$/i.test(rain) ? rain.replace(/mm$/i, "mm/h") : `${rain}mm/h`)}</small>` : "";
    return `<article class="weather-day-card level-${escapeHtml(dayLevel)}" data-emphasis="${importance}">${badge ? `<em class="weather-day-badge">${escapeHtml(badge)}</em>` : ""}<strong>${escapeHtml(day.date.slice(5))}</strong><span>${escapeHtml(summary.weatherText || "정보 없음")}</span><small>${escapeHtml(temperatureLabel(summary))}${escapeHtml(pop)}</small>${rainfall}</article>`;
  }).join("");
  renderWeatherDetails(context, visibleSignals, regionId);
  els.weatherRiskList.innerHTML = visibleSignals.map((signal, index) => {
    const regions = (signal.regionIds || []).map(id => REGION_LABELS[id] || id).join(" · ");
    const saved = attachedSignals.get(signal.id) || { selected: true, editorLevel: null, editorNote: "" };
    const selected = saved.selected !== false ? "checked" : "";
    const disabled = finalized ? "disabled" : "";
    const levelOptions = [["", "자동 단계"], ["critical", "긴급"], ["watch", "주의"], ["info", "참고"], ["normal", "정상"], ["unknown", "확인 불가"]].map(([value, label]) => `<option value="${value}" ${saved.editorLevel === value ? "selected" : ""}>${label}</option>`).join("");
    const evidenceTitle = signal.evidence?.[0]?.title || "기상특보 근거 확인 불가";
    const preliminary = evidenceTitle.includes("예비특보");
    const period = `${signal.startsAt ? formatDateTime(signal.startsAt) : "시작 미상"}${signal.endsAt ? ` ~ ${formatDateTime(signal.endsAt)}` : "부터"}`;
    return `<article class="weather-risk-card level-${escapeHtml(signal.level)}" data-weather-signal-id="${escapeHtml(signal.id)}"><span class="weather-risk-rank">${String(index + 1).padStart(2, "0")}</span><div><h3>${escapeHtml(HAZARD_LABELS[signal.hazard] || signal.hazard)} <em>${escapeHtml(LEVEL_LABELS[signal.level] || signal.level)}</em>${preliminary ? '<em class="preliminary">예비</em>' : ""}</h3><p><b>${escapeHtml(regions || "전국")}</b> · ${escapeHtml((signal.electricalRisks || []).join(", "))}</p><small><b>권고 확인</b> ${escapeHtml((signal.recommendedChecks || []).join(" · "))}</small><div class="weather-risk-evidence"><b>공식 근거</b><span>${escapeHtml(evidenceTitle)}</span><small>${escapeHtml(period)}</small></div><div class="weather-signal-editor no-print"><label><input class="weather-signal-selected" type="checkbox" ${selected} ${disabled}> 보고 반영</label><select class="weather-signal-level" ${disabled}>${levelOptions}</select><input class="weather-signal-note" type="text" maxlength="1000" value="${escapeHtml(saved.editorNote || "")}" placeholder="담당자 확인 메모" ${disabled}></div></div></article>`;
  }).join("") || '<p class="weather-empty">최신 특보 기준 별도 전기재해 위험 신호가 없습니다.</p>';

  if (state.weatherLoading) {
    els.weatherStatus.className = "weather-status busy";
    els.weatherStatus.textContent = "기존 정상 데이터를 유지하면서 새 기상정보를 수집하고 있습니다.";
    els.weatherCompactNotice.textContent = "새 기상정보 수집 중 · 기존 정상 정보를 표시합니다.";
  } else if (sourceWarnings.length) {
    els.weatherStatus.className = "weather-status warning";
    els.weatherStatus.textContent = `일부 기상정보 오류: ${sourceWarnings.map(([name, item]) => `${name} ${item.status}`).join(" · ")}`;
    els.weatherCompactNotice.textContent = "일부 기상정보 확인 필요 · 상세 화면에서 오류 상태를 확인하세요.";
  } else if (weather.newerContextAvailable) {
    els.weatherStatus.className = "weather-status warning";
    els.weatherStatus.textContent = "검토한 보고용 기상정보보다 최신 발표가 있습니다. 다시 검토해 주세요.";
    els.weatherCompactNotice.textContent = "검토 이후 최신 발표가 있습니다. 상세 화면에서 다시 확인해 주세요.";
  } else if (reviewed) {
    els.weatherStatus.className = "weather-status ready";
    els.weatherStatus.textContent = `${formatDateTime(weather.attached.reviewedAt)} 검토 완료 · CEO 보고에 반영됩니다.`;
    els.weatherCompactNotice.textContent = "담당자 검토 완료 · CEO 보고 반영 상태";
  } else {
    els.weatherStatus.className = "weather-status";
    els.weatherStatus.textContent = "최신 기상정보입니다. CEO 보고에 반영하려면 담당자 검토를 완료해 주세요.";
    els.weatherCompactNotice.textContent = "최신 정보 표시 중 · CEO 보고 반영은 상세 화면에서 검토 후 확정합니다.";
  }
  els.weatherReviewBtn.textContent = reviewed ? "검토 내용 저장" : "검토 완료·CEO 보고 반영";
}

function signalSelections(context) {
  const editors = new Map(
    [...els.weatherRiskList.querySelectorAll("[data-weather-signal-id]")].map(card => [card.dataset.weatherSignalId, card])
  );
  const saved = new Map((state.weather?.attached?.signals || []).map(item => [item.id, item]));
  return (context.riskSignals || []).map(signal => {
    const card = editors.get(signal.id);
    const previous = saved.get(signal.id) || {};
    return {
      id: signal.id,
      selected: card ? card.querySelector(".weather-signal-selected").checked : previous.selected !== false,
      editorLevel: card ? card.querySelector(".weather-signal-level").value || null : previous.editorLevel || null,
      editorNote: card ? card.querySelector(".weather-signal-note").value.trim() : previous.editorNote || "",
    };
  });
}

export async function refreshWeather() {
  if (state.date !== localDateKey()) {
    showToast("기상정보는 오늘 보고일만 새로 수집할 수 있습니다.", "error");
    return;
  }
  state.weatherLoading = true;
  renderWeather();
  try {
    const result = await api.refreshWeather(state.date);
    state.weather = result.data;
    showToast("기상청 예보·특보를 새로 수집했습니다.", "success");
  } catch (error) {
    showToast(`기상정보 수집 실패: ${friendlyError(error)}`, "error");
    const latest = await api.getWeatherBriefing(state.date).catch(() => null);
    if (latest) state.weather = latest.data;
  } finally {
    state.weatherLoading = false;
    renderWeather();
  }
}

export async function toggleWeatherReview() {
  const weather = state.weather || {};
  const context = weather.latestContext;
  if (!context) return;
  try {
    const result = await api.putBriefingWeather(state.date, {
      expectedRevision: state.revision,
      contextId: context.id,
      includeInReport: true,
      reviewStatus: "reviewed",
      selectedSignals: signalSelections(context),
      editorNote: weather.attached?.editorNote || "최신 기상청 발표와 위험 신호를 확인함",
    });
    state.revision = result.data.briefing.revision;
    state.weather = result.data.weather;
    renderWeather();
    showToast("기상정보 검토 내용을 저장하고 CEO 보고에 반영했습니다.", "success");
  } catch (error) {
    showToast(`기상정보 검토 저장 실패: ${friendlyError(error)}`, "error");
  }
}

export async function excludeWeatherFromReport() {
  const weather = state.weather || {};
  const context = weather.attachedContext || weather.latestContext;
  if (!context || !weather.attached) return;
  try {
    const result = await api.putBriefingWeather(state.date, {
      expectedRevision: state.revision,
      contextId: weather.attached.contextId,
      includeInReport: false,
      reviewStatus: "pending",
      selectedSignals: weather.attached.signals || [],
      editorNote: weather.attached.editorNote || "",
    });
    state.revision = result.data.briefing.revision;
    state.weather = result.data.weather;
    renderWeather();
    showToast("기상정보를 CEO 보고에서 제외했습니다.", "success");
  } catch (error) {
    showToast(`기상정보 보고 제외 실패: ${friendlyError(error)}`, "error");
  }
}
