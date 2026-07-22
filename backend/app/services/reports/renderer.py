from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from html import escape
from typing import Any

from backend.app.services.extraction.cleaner import clean_article_text, clean_text
from backend.app.services.extraction.evidence_validation import body_errors, validate_source
from backend.app.services.reports.report_draft import content_from_plain_text

KST = timezone(timedelta(hours=9))

CATEGORY_LABELS = {
    "kesco_direct": "공사 직접 보도",
    "direct": "공사 직접 보도",
    "kesco_reputation": "공사 평판",
    "presidential_message": "대통령실 메시지",
    "prime_minister_message": "국무총리·총리실 메시지",
    "climate_minister_message": "기후에너지환경부 장관 메시지",
    "government_meeting": "국무회의·정부위원회",
    "public_evaluation": "공공기관 경영평가",
    "public_operations": "공공기관 운영정책",
    "kesco_governance": "공사 경영·거버넌스",
    "assembly_law": "국회·국정감사·법안",
    "electrical_accident": "전기화재·감전 사고",
    "power_outage": "정전·전력공급 장애",
    "weather": "기상",
    "major_fire_breaking": "중대화재·속보",
    "new_industry_safety": "신산업 설비안전",
    "law_standard_plan": "법령·기준·기본계획",
    "kesco_achievement": "공사 성과·예방활동",
    "strategic_trend": "전력망·전략동향",
    "renewable_ess_industry": "재생에너지·ESS 산업",
    "ev_industry": "전기차·충전인프라",
    "macro_economy": "에너지·공공요금 거시환경",
    "ai_trend": "AI·전력·공공부문",
    "other": "기타",
}
RISK_LABELS = {"critical": "고위험", "watch": "주의", "routine": "일반"}
SENTIMENT_LABELS = {"positive": "긍정", "neutral": "중립", "negative": "부정"}
ISSUE_STATUS_LABELS = {
    "new": "신규",
    "expanding": "확산",
    "ongoing": "지속",
    "cooling": "진정",
    "closed": "종료",
}
ISSUE_PRIORITY_LABELS = {"required": "필수 보고", "review": "검토", "reference": "참고"}
WEEKDAY_LABELS = ["월", "화", "수", "목", "금", "토", "일"]
DIRECT_CATEGORIES = {"direct", "kesco_direct"}


def _text(value: Any, fallback: str = "") -> str:
    return escape(str(value if value not in (None, "") else fallback))


def _datetime_label(value: Any, fallback: str, *, with_year: bool = False) -> str:
    if value in (None, ""):
        return fallback
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(KST)
    return parsed.strftime("%Y. %m. %d %H:%M" if with_year else "%m월 %d일 %H:%M")


def _article_body_preview(item: dict[str, Any]) -> str:
    body_text = str(item.get("bodyText") or "")
    description = clean_text(item.get("description"))
    if not body_text:
        return description or "본문 미확보"

    title = clean_text(item.get("title"))
    source = clean_text(item.get("source"))
    cleaned = clean_text(clean_article_text(body_text, title=title).text)
    if description and "body_contaminated" in body_errors(cleaned, status="success_full"):
        return description
    title_candidates = [title]
    if source:
        without_source = re.sub(rf"\s*-\s*{re.escape(source)}\s*$", "", title).strip()
        if without_source and without_source != title:
            title_candidates.append(without_source)
    for candidate in sorted(title_candidates, key=len, reverse=True):
        if candidate and cleaned.startswith(candidate):
            cleaned = cleaned[len(candidate) :].lstrip(" -·|:：")
            break
    return cleaned or description or "본문 미확보"


def _article_source_label(item: dict[str, Any]) -> str:
    source = str(item.get("source") or "")
    url = str(item.get("url") or item.get("canonicalUrl") or "")
    validation = validate_source(
        raw_source=str(item.get("rawSource") or source),
        displayed_source=str(item.get("normalizedSource") or source),
        source_url=url,
        resolved_url=url,
        canonical_url=str(item.get("canonicalUrl") or ""),
        page_publisher=str(item.get("pagePublisher") or ""),
    )
    return validation.source or source or "출처 미상"


def _claim(value: Any) -> tuple[str, list[str]]:
    if not isinstance(value, dict):
        return "", []
    return str(value.get("text") or ""), list(value.get("articleIds") or [])


def _analysis_for_display(analysis: dict[str, Any]) -> dict[str, Any]:
    management_text, evidence_ids = _claim(analysis.get("managementMessage"))
    has_separate_sections = bool(
        _claim(analysis.get("situationSummary"))[0]
        or analysis.get("keyIssues")
        or analysis.get("decisionPoints")
        or analysis.get("actionItems")
        or _claim(analysis.get("riskOutlook"))[0]
    )
    if not management_text or has_separate_sections:
        return analysis
    parsed = content_from_plain_text(management_text, evidence_ids)
    if parsed["managementMessage"]["text"] == management_text:
        return analysis
    return {**analysis, **parsed}


def _render_lead(value: Any) -> str:
    text, _ = _claim(value)
    if not text:
        return '<p class="empty">작성된 오늘 한줄이 없습니다.</p>'
    return f'<div class="analysis-lead"><p>{_text(text)}</p></div>'


def _render_trend_analysis(analysis: dict[str, Any]) -> str:
    situation_text, _ = _claim(analysis.get("situationSummary"))
    if not situation_text:
        return '<p class="empty">작성된 언론 동향 분석이 없습니다.</p>'
    return f'<div class="analysis-prose"><p>{_text(situation_text)}</p></div>'


def _render_management_reference(analysis: dict[str, Any]) -> str:
    items: list[str] = []
    for item in analysis.get("actionItems") or []:
        if item.get("kescoJurisdiction") not in (None, "DIRECT", "COLLABORATIVE"):
            continue
        if item.get("ownerType") == "EXTERNAL_AGENCY":
            continue
        action = str(item.get("action") or "").strip()
        if action:
            items.append(action)
    if not items:
        return '<p class="empty">직접적인 경영 현안은 제한적입니다.</p>'
    combined = "\n\n".join(items)
    return f'<div class="analysis-prose"><p>{_text(combined)}</p></div>'


def _render_monitoring_reference(analysis: dict[str, Any]) -> str:
    items: list[str] = []
    for item in analysis.get("keyIssues") or []:
        if item.get("urgency") != "reference" and item.get("kescoJurisdiction") != "MONITORING":
            continue
        text = " ".join(
            value.strip()
            for value in (
                str(item.get("summary") or ""),
                str(item.get("managementImpact") or ""),
            )
            if value.strip()
        )
        if text:
            items.append(text)
    if not items:
        return ""
    combined = "\n\n".join(items)
    return f'<div class="analysis-prose"><p>{_text(combined)}</p></div>'


def _article_badges(item: dict[str, Any]) -> str:
    badges = []
    category = item.get("category")
    if category:
        badges.append(f'<span class="badge cat">{_text(CATEGORY_LABELS.get(category, category))}</span>')
    risk = item.get("risk")
    if risk in ("critical", "watch"):
        badges.append(f'<span class="badge risk-{_text(risk)}">{RISK_LABELS[risk]}</span>')
    sentiment = item.get("sentiment")
    if sentiment in ("negative", "positive"):
        badges.append(f'<span class="badge tone-{_text(sentiment)}">{SENTIMENT_LABELS[sentiment]}</span>')
    if item.get("starred"):
        badges.append('<span class="badge star">중요 표시</span>')
    return f'<div class="badges">{"".join(badges)}</div>' if badges else ""


def _kpi_strip(snapshot: dict[str, Any]) -> str:
    articles = snapshot.get("articles") or []
    issues = snapshot.get("issues") or []
    critical = sum(1 for item in articles if item.get("risk") == "critical")
    watch = sum(1 for item in articles if item.get("risk") == "watch")
    direct = sum(1 for item in articles if item.get("category") in DIRECT_CATEGORIES)
    tiles = [
        ("분석 자료", f"선정 기사 {len(articles)}건", ""),
        ("주요 관찰", f"고위험 {critical} · 주의 {watch}", "alert" if critical else "warn" if watch else "calm"),
        ("공사 관련", f"직접 보도 {direct}건 · 이슈 {len(issues)}건", ""),
    ]
    return "".join(
        f'<div class="kpi {tone}"><small>{_text(label)}</small><strong>{_text(value)}</strong></div>'
        for label, value, tone in tiles
    )


def _critical_alerts(snapshot: dict[str, Any]) -> str:
    items = [item for item in snapshot.get("articles") or [] if item.get("risk") == "critical"]
    if not items:
        return ""
    rows = "".join(
        f'<li><a href="#article-{_text(item.get("id"))}">{_text(item.get("title"), "제목 없음")}</a>'
        f'<span>{_text(item.get("source"), "출처 미상")}</span></li>'
        for item in items
    )
    return (
        f'<div class="alert-box"><h3>긴급 확인 필요 보도 {len(items)}건</h3>'
        f"<ul>{rows}</ul></div>"
    )


WEATHER_REGION_LABELS = {
    "national": "전국",
    "capital": "수도권",
    "gangwon": "강원",
    "chungcheong": "충청",
    "honam": "호남",
    "yeongnam": "영남",
    "jeju": "제주",
}


def _weather_day_date(day: dict[str, Any]) -> date | None:
    try:
        return date.fromisoformat(str(day.get("date") or ""))
    except ValueError:
        return None


def _weather_period_label(days: list[dict[str, Any]]) -> str:
    dated = [parsed for day in days if (parsed := _weather_day_date(day)) is not None]
    if not dated:
        return "날짜 미상"
    labels = [f"{item.month}. {item.day}" for item in dated]
    if len(dated) == 1:
        return labels[0]
    consecutive = all(
        current == previous + timedelta(days=1)
        for previous, current in zip(dated, dated[1:], strict=False)
    )
    if consecutive:
        end = str(dated[-1].day) if dated[0].month == dated[-1].month else labels[-1]
        return f"{labels[0]}~{end}"
    if all(item.month == dated[0].month for item in dated):
        return f"{dated[0].month}. " + "·".join(str(item.day) for item in dated)
    return "·".join(labels)


def _weather_periods(
    days: list[dict[str, Any]], predicate: Any,
) -> list[list[dict[str, Any]]]:
    periods: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    previous_date: date | None = None
    for day in days:
        parsed = _weather_day_date(day)
        if not predicate(day):
            if current:
                periods.append(current)
                current = []
            previous_date = None
            continue
        if current and parsed is not None and previous_date is not None:
            if parsed != previous_date + timedelta(days=1):
                periods.append(current)
                current = []
        current.append(day)
        previous_date = parsed
    if current:
        periods.append(current)
    return periods


def _precipitation_peak(amount: Any) -> float | None:
    if not isinstance(amount, dict):
        return None
    value = amount.get("max")
    if value is None:
        value = amount.get("min")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _millimeter_label(value: float) -> str:
    return str(int(value)) if value.is_integer() else f"{value:.1f}"


def _weather_region_summary(
    days: list[dict[str, Any]], signals: list[dict[str, Any]], hazard: str,
) -> str:
    scores: dict[str, float] = {}
    for day in days:
        for region in day.get("regions") or []:
            region_id = str(region.get("regionId") or "")
            if hazard == "heavy_rain":
                value = _precipitation_peak(region.get("maxHourlyPrecipitation"))
                threshold = 10
            else:
                value = (region.get("temperature") or {}).get("max")
                threshold = 33
            if region_id and value is not None and value >= threshold:
                scores[region_id] = max(scores.get(region_id, 0), float(value))
    ordered = [item[0] for item in sorted(scores.items(), key=lambda item: -item[1])]
    if not ordered:
        ordered = list(
            dict.fromkeys(
                str(region_id)
                for signal in signals
                if signal.get("hazard") == hazard
                for region_id in (signal.get("regionIds") or [])
            )
        )
    labels = [WEATHER_REGION_LABELS.get(region_id, region_id) for region_id in ordered]
    return "·".join(labels[:3]) + (" 등" if len(labels) > 3 else "")


def _weather_concern(signals: list[dict[str, Any]], hazard: str) -> str:
    hazards = {"폭우": {"heavy_rain", "typhoon"}, "폭염": {"heat"}}
    concerns = list(
        dict.fromkeys(
            str(risk)
            for signal in signals
            if signal.get("hazard") in hazards.get(hazard, set())
            for risk in (signal.get("electricalRisks") or [])
            if risk
        )
    )
    if concerns:
        return "·".join(concerns[:2])
    return {
        "폭우": "저지대 전기설비 침수·누전·감전",
        "폭염": "냉방설비 배선·접속부 과열",
    }.get(hazard, "예보 변동 확인 필요")


def _weather_signal_score(signals: list[dict[str, Any]], hazards: set[str]) -> int:
    levels = {
        str(signal.get("level") or "normal")
        for signal in signals
        if signal.get("hazard") in hazards
    }
    return 20 if "critical" in levels else 10 if "watch" in levels else 0


def _render_weather_forecasts(context: dict[str, Any]) -> str:
    days = list(context.get("days") or [])[:7]
    signals = list(context.get("riskSignals") or [])
    forecasts: list[tuple[int, str, str, str]] = []
    rain_periods = _weather_periods(
        days,
        lambda day: _precipitation_peak(day.get("maxHourlyPrecipitation")) is not None,
    )
    for period in rain_periods[:2]:
        hourly = max(
            (_precipitation_peak(day.get("maxHourlyPrecipitation")) or 0 for day in period),
            default=0,
        )
        daily = max(
            (_precipitation_peak(day.get("dailyPrecipitation")) or 0 for day in period),
            default=0,
        )
        hazard = "폭우" if hourly >= 30 or daily >= 80 else "비"
        details = f"최대 시간당 {_millimeter_label(hourly)}mm"
        if daily:
            details += f" · 일 최대 {_millimeter_label(daily)}mm"
        regions = _weather_region_summary(period, signals, "heavy_rain")
        if regions:
            details += f" / {regions}"
        score = (
            100 if hourly >= 30 or daily >= 80
            else 70 if hourly >= 10 or daily >= 30
            else 30
        ) + _weather_signal_score(signals, {"heavy_rain", "typhoon"})
        forecasts.append(
            (
                score,
                hazard,
                f"{_weather_period_label(period)}　{details}",
                _weather_concern(signals, hazard),
            )
        )

    heat_days = [
        day
        for day in days
        if ((day.get("temperature") or {}).get("max") or -999) >= 33
    ]
    if heat_days:
        maximum = max((day.get("temperature") or {}).get("max") for day in heat_days)
        regions = _weather_region_summary(heat_days, signals, "heat")
        details = f"최고 {maximum}℃"
        if regions:
            details += f" / {regions}"
        score = (90 if maximum >= 35 else 60) + _weather_signal_score(signals, {"heat"})
        forecasts.append(
            (
                score,
                "폭염",
                f"{_weather_period_label(heat_days)}　{details}",
                _weather_concern(signals, "폭염"),
            )
        )

    if not forecasts:
        forecasts.append(
            (0, "예보", f"{_weather_period_label(days)}　특이 기상 없음", "예보 변동 확인 필요")
        )

    _, hazard, summary, concern = max(forecasts, key=lambda item: item[0])
    return (
        f'<article class="weather-forecast weather-{_text(hazard)}">'
        f'<strong>({_text(hazard)})</strong><p><b>{_text(summary)}</b>'
        f'<span>우려: {_text(concern)}</span></p></article>'
    )


def _render_weather(snapshot: dict[str, Any]) -> str:
    weather = snapshot.get("weather") or {}
    context = weather.get("context") or {}
    attachment = weather.get("attachment") or {}
    if not context or not attachment.get("includeInReport"):
        return ""
    return (
        '<section class="section weather-section"><div class="weather-heading"><h2>'
        '기상 특이사항</h2>'
        f'<small>기상청 {_text(_datetime_label(context.get("issuedAt"), "시각 미상"))} 발표</small></div>'
        f'<div class="weather-forecasts">{_render_weather_forecasts(context)}</div>'
        '</section>'
    )


def _issue_cards(snapshot: dict[str, Any]) -> str:
    issues = snapshot.get("issues") or []
    articles_by_id = {item.get("id"): item for item in snapshot.get("articles") or []}
    if issues:
        ordered = sorted(
            issues,
            key=lambda item: (
                -(item.get("effectiveReviewStars") or 0),
                item.get("autoReviewRank") or 999999,
                item.get("id") or "",
            ),
        )[:5]
        cards = []
        for index, item in enumerate(ordered, 1):
            stars = int(item.get("effectiveReviewStars") or 1)
            status = item.get("effectiveStatus")
            priority = item.get("effectivePriority")
            article_ids = item.get("articleIds") or []
            badges = [
                f'<span class="badge status">{_text(ISSUE_STATUS_LABELS.get(status, status), "상태 미지정")}</span>'
            ]
            if priority:
                badges.append(
                    f'<span class="badge priority-{_text(priority)}">'
                    f"{_text(ISSUE_PRIORITY_LABELS.get(priority, priority))}</span>"
                )
            if item.get("directMention"):
                badges.append('<span class="badge direct">공사 직접 언급</span>')
            selected_related = [
                articles_by_id[article_id]
                for article_id in article_ids
                if article_id in articles_by_id
            ]
            representative = selected_related[0] if selected_related else None
            rep_html = (
                f'<p class="issue-rep">대표 보도 <a href="#article-{_text(representative.get("id"))}">'
                f'{_text(representative.get("title"), "제목 없음")}</a>'
                f' <span>({_text(representative.get("source"), "출처 미상")})</span></p>'
                if representative
                else ""
            )
            note = (item.get("briefingState") or {}).get("note") or ""
            reason = item.get("editorReviewReason") or ""
            note_html = f'<p class="issue-note">담당자 메모: {_text(note)}</p>' if note else ""
            reason_html = f'<p class="issue-note">선정 사유: {_text(reason)}</p>' if reason else ""
            cards.append(
                f'<article class="issue"><div class="issue-head"><span class="rank">{index:02d}</span>'
                f'<h3>{_text(item.get("effectiveTitle"), "제목 없음")}</h3></div>'
                f'<div class="issue-meta"><span class="stars">{"★" * stars}{"☆" * (5 - stars)}</span>'
                f'{"".join(badges)}<span class="count">관련 보도 {len(article_ids)}건 · 자동평가 '
                f'{_text(item.get("autoReviewRank"), "-")}위</span></div>'
                f"{rep_html}{note_html}{reason_html}</article>"
            )
        return "".join(cards)
    articles = snapshot.get("articles") or []
    return "".join(
        f'<article class="issue"><div class="issue-head"><span class="rank">{index:02d}</span>'
        f'<h3>{_text(item.get("title"))}</h3></div>'
        f'<div class="issue-meta"><span class="count">{_text(item.get("source"), "출처 미상")}</span></div></article>'
        for index, item in enumerate(articles[:3], 1)
    ) or '<p class="empty">선정된 핵심 이슈가 없습니다.</p>'


def _article_cards(
    snapshot: dict[str, Any], *, direct_only: bool = False, include_anchors: bool = True,
) -> str:
    articles = snapshot.get("articles") or []
    if direct_only:
        articles = [item for item in articles if item.get("category") in DIRECT_CATEGORIES]
    if not articles:
        return '<p class="empty">해당 기사가 없습니다.</p>'
    cards = []
    for editor_index, item in enumerate(articles):
        url = str(item.get("url") or "")
        title = _text(item.get("title"), "제목 없음")
        has_external_url = url.startswith(("http://", "https://"))
        anchor = f' id="article-{_text(item.get("id"))}"' if include_anchors else ""
        risk_rank = {"critical": 0, "watch": 1, "routine": 2}.get(item.get("risk"), 3)
        priority_score = item.get("priorityScore")
        try:
            priority_score = float(priority_score)
        except (TypeError, ValueError):
            priority_score = 0
        body_preview = _article_body_preview(item)
        source_label = _article_source_label(item)
        article_main = (
            f'<div class="article-main"><div class="article-title-row"><h3>{title}</h3>'
            f'<p class="meta">{_text(source_label)} · '
            f'{_text(_datetime_label(item.get("pubDate"), "시각 미상"))}</p></div>'
            f'<p class="desc">{_text(body_preview)}</p></div>'
        )
        linked_main = (
            f'<a class="article-link" href="{_text(url)}" target="_blank" '
            f'rel="noopener noreferrer">{article_main}</a>'
            if has_external_url
            else article_main
        )
        cards.append(
            f'<article class="article"{anchor} data-editor-index="{editor_index}" '
            f'data-starred="{1 if item.get("starred") else 0}" data-risk-rank="{risk_rank}" '
            f'data-priority-score="{priority_score}">'
            f'<span class="article-number" aria-hidden="true">{editor_index + 1:02d}</span>'
            f'{linked_main}</article>'
        )
    return "".join(cards)


def render_report(snapshot: dict[str, Any], *, preview: bool = False) -> str:
    briefing = snapshot.get("briefing") or {}
    report_date = str(snapshot.get("reportDate") or "")
    try:
        parsed = date.fromisoformat(report_date)
        date_label = f"{parsed.strftime('%Y. %m. %d')} ({WEEKDAY_LABELS[parsed.weekday()]})"
    except ValueError:
        date_label = report_date
    version = snapshot.get("version")
    badge = "작업본 미리보기" if preview else f"최종본 v{version}"
    badge_class = "preview" if preview else "final"
    ai_run = snapshot.get("aiRun") or {}
    report_draft = snapshot.get("reportDraft") or {}
    analysis = _analysis_for_display(
        report_draft.get("content") or ((ai_run.get("response") or {}).get("analysis") or {})
    )
    weather_html = _render_weather(snapshot)
    article_count = len(snapshot.get("articles") or [])
    article_layout_class = " is-twelve" if article_count == 12 else ""
    styles = """
    :root{color-scheme:light;--navy:#12243a;--navy2:#173b51;--teal:#087f76;--mint:#dff3ef;--red:#b02a2a;--amber:#b06a12;--line:#d7dfe3;--soft:#f4f7f7;--ink:#22303a;--muted:#66757f;--copy-size:14px;--report-scale:.93}
    *{box-sizing:border-box;-webkit-print-color-adjust:exact;print-color-adjust:exact}
    body{margin:0;background:#e8edef;color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Noto Sans KR",sans-serif;line-height:1.65;font-size:14px}
    .toolbar{position:sticky;top:0;z-index:2;display:flex;justify-content:flex-end;gap:8px;padding:10px 20px;background:#10253cee}
    .toolbar a,.toolbar button{border:1px solid #ffffff55;border-radius:8px;padding:7px 14px;background:#fff;color:var(--navy);font-weight:700;font-size:13px;text-decoration:none;cursor:pointer}
    .toolbar button[aria-pressed="true"]{border-color:#77d6cd;background:#dff3ef;color:#075f59}
    main{width:min(210mm,calc(100% - 28px));margin:24px auto 48px;display:grid;gap:24px}
    .report-page{position:relative;width:210mm;height:297mm;overflow:hidden;padding:12mm 7mm;background:#fff;box-shadow:0 14px 45px #10253c1c}
    .page-inner{width:100%;transform:scale(var(--report-scale));transform-origin:top center}
    .masthead{position:relative;overflow:hidden;padding:22px 28px 20px;background:linear-gradient(125deg,#0d2138 0%,#173e52 72%,#0b756e 150%);color:#fff}
    .masthead:after{content:"";position:absolute;right:-90px;bottom:-145px;width:340px;height:340px;border:1px solid #ffffff1f;border-radius:50%;box-shadow:0 0 0 55px #ffffff0a,0 0 0 110px #ffffff08}
    .doc-meta{display:flex;justify-content:space-between;padding-bottom:9px;margin-bottom:11px;border-bottom:1px solid #ffffff2e;font-size:11px;letter-spacing:.04em;color:#c7d5e0;font-weight:600}
    .masthead .top{display:flex;justify-content:space-between;align-items:flex-end;gap:20px}
    .eyebrow{margin:0;color:#7ed7ce;font-size:11.5px;letter-spacing:.2em;text-transform:uppercase;font-weight:800}
    .masthead h1{margin:5px 0 0;font-size:28px;letter-spacing:-.035em}
    .masthead .subtitle{margin:4px 0 0;color:#c7d8df;font-size:11.5px}
    .date{text-align:right}.date strong{display:block;font-size:19px;font-weight:800}
    .date small{display:block;margin-top:6px;color:#c1d0db;font-size:12px}
    .status{display:inline-block;border-radius:999px;padding:4px 10px;font-size:10.5px;font-weight:800;margin-top:7px}
    .status.preview{background:#fff1d6;color:#8a5a10}.status.final{background:#e3f3f0;color:#086b63}
    .kpis{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;margin:0;padding:0 52px;background:#dbe3e5;border-bottom:1px solid var(--line)}
    .kpi{padding:15px 18px 14px;border:0;background:#f7f9f9}
    .kpi small{display:block;color:var(--muted);font-size:11px;font-weight:700;letter-spacing:.03em}
    .kpi strong{display:block;margin-top:4px;font-size:17px;color:var(--navy);letter-spacing:-.01em}
    .kpi.alert{border-color:#e4b6b6;background:#fdf3f3}.kpi.alert strong{color:var(--red)}
    .kpi.warn strong{color:var(--amber)}.kpi.calm strong{color:var(--teal)}
    .body{padding:0 4px 4px}
    .section{margin-top:20px}
    .section h2{display:flex;align-items:center;gap:12px;margin:0 0 11px;padding-bottom:7px;border-bottom:1px solid #aab8bf;color:var(--navy);font-size:17px;letter-spacing:-.025em}
    .sec-num{display:inline-grid;place-items:center;width:28px;height:28px;border-radius:50%;background:var(--navy);color:#fff;font-size:12px;font-weight:800}
    .sec-tag{border-radius:6px;padding:2px 8px;background:var(--navy);color:#fff;font-size:12px;font-weight:800}
    .analysis-lead{position:relative;padding:16px 18px;border:1px solid #badbd6;border-radius:4px 16px 16px 4px;background:linear-gradient(135deg,#effaf7,#f8fbfb);box-shadow:inset 5px 0 var(--teal)}
    .analysis-lead p{margin:0;white-space:pre-wrap;color:#172e3b;font-size:15.4px;font-weight:700;line-height:1.6;letter-spacing:-.012em}
    .analysis-prose{padding:2px 2px 4px}.analysis-prose>p{margin:0;white-space:pre-wrap;font-size:var(--copy-size);line-height:1.65;color:#293943}
    .alert-box{margin-top:14px;padding:16px 18px;border:1px solid #e4b6b6;border-left:5px solid var(--red);border-radius:8px;background:#fdf3f3}
    .alert-box h3{margin:0 0 8px;color:var(--red);font-size:14px}
    .alert-box ul{margin:0;padding-left:18px}.alert-box li{margin:3px 0;font-size:13.5px}
    .alert-box a{color:#8f2222;font-weight:700}.alert-box li span{margin-left:6px;color:var(--muted);font-size:12px}
    .issues{display:grid;gap:10px}
    .issue{padding:16px 18px;border:1px solid var(--line);border-left:4px solid var(--navy);border-radius:10px;break-inside:avoid}
    .issue-head{display:flex;gap:12px;align-items:baseline}
    .rank{color:var(--teal);font-size:13px;font-weight:800}
    .issue h3{margin:0;font-size:15.5px;color:var(--navy)}
    .issue-meta{display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin-top:9px}
    .stars{color:#c9910c;font-size:13px;letter-spacing:.1em}
    .count{color:var(--muted);font-size:12px}
    .issue-rep{margin:9px 0 0;font-size:13px}.issue-rep a{color:var(--navy)}.issue-rep span{color:var(--muted);font-size:12px}
    .issue-note{margin:7px 0 0;padding:7px 10px;border-radius:6px;background:#fff8e9;color:#6d5324;font-size:12.5px}
    .badge{display:inline-block;border-radius:999px;padding:2px 9px;font-size:11px;font-weight:700;background:#eef2f4;color:#51616c}
    .badge.status{background:#e5edf5;color:#2c5379}.badge.direct{background:#e3f3f0;color:#086b63}
    .badge.priority-required{background:#fdeaea;color:var(--red)}.badge.priority-review{background:#fff3e0;color:var(--amber)}
    .badge.cat{background:#eef2f4;color:#51616c}
    .badge.risk-critical{background:#fdeaea;color:var(--red)}.badge.risk-watch{background:#fff3e0;color:var(--amber)}
    .badge.tone-negative{background:#f3e8f5;color:#7b3f8a}.badge.tone-positive{background:#e3f3f0;color:#086b63}
    .badge.star{background:#fff3d3;color:#8a6410}
    .appendix-masthead{position:relative;overflow:hidden;padding:13px 20px 14px;border-top:5px solid #35b8aa;border-left:0;background:linear-gradient(118deg,#0d2138 0%,#173e52 74%,#0b756e 145%);color:#fff;box-shadow:0 6px 16px #10253c20}
    .appendix-masthead:after{content:"";position:absolute;right:-42px;bottom:-84px;width:145px;height:145px;border:1px solid #ffffff24;border-radius:50%;box-shadow:0 0 0 27px #ffffff0a,0 0 0 54px #ffffff08}
    .appendix-masthead .doc-meta{position:relative;z-index:1;padding-bottom:6px;margin-bottom:9px;border-bottom-color:#ffffff38;color:#cfdae1;font-size:10px}.appendix-title{position:relative;z-index:1;display:grid;grid-template-columns:auto auto 1fr;align-items:baseline;gap:0 13px}.appendix-title .eyebrow{color:#7ed7ce;font-size:10px}.appendix-title h2{margin:0;color:#fff;font-size:24px;line-height:1.15;letter-spacing:-.035em}.appendix-count{justify-self:end;display:flex;align-items:center;gap:8px;padding:5px 11px;border:1px solid #ffffff70;border-radius:999px;background:#ffffffed;color:#08756e;box-shadow:0 3px 10px #0718272e}.appendix-count strong{font-size:19px;line-height:1}.appendix-count span{font-size:8.5px;line-height:1.15;letter-spacing:.09em;font-weight:900}
    .articles{counter-reset:article-card;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));grid-auto-rows:minmax(108px,auto);gap:10px 11px;margin-top:18px;min-width:0}
    .articles.is-twelve{grid-template-rows:repeat(6,minmax(0,1fr));grid-auto-rows:unset;height:264mm}
    .article{position:relative;display:block;min-width:0;overflow:hidden;padding:12px 13px 11px 50px;border:1px solid #ccd8dd;border-top:3px solid var(--navy);border-radius:4px 12px 12px 4px;background:linear-gradient(145deg,#fff 0%,#fbfdfd 100%);box-shadow:0 4px 13px #10253c0a;break-inside:avoid}
    .article-number{position:absolute;left:12px;top:12px;display:grid;place-items:center;width:27px;height:27px;border-radius:8px 2px 8px 2px;background:var(--navy);color:#fff;font-size:10.5px;font-weight:900;letter-spacing:.04em}.article:after{content:"";position:absolute;right:-16px;top:-18px;width:44px;height:44px;border-radius:50%;background:#35b8aa18}
    .article-link{display:block;height:100%;min-width:0;color:inherit;text-decoration:none}.article-main{display:grid;height:100%;min-width:0;grid-template-rows:64px minmax(0,1fr)}.article-title-row{display:flex;min-width:0;height:64px;flex-direction:column}.article h3{display:-webkit-box;min-width:0;height:2.76em;min-height:2.76em;margin:0;overflow:hidden;color:var(--navy);font-size:14.8px;line-height:1.38;letter-spacing:-.02em;line-clamp:2;-webkit-box-orient:vertical;-webkit-line-clamp:2}
    .article .meta{order:-1;margin:0 0 5px;color:var(--teal);font-size:10.5px;font-weight:800;letter-spacing:.01em;white-space:nowrap}
    .article .badges{margin-top:7px;display:flex;flex-wrap:wrap;gap:4px}
    .article .desc{display:-webkit-box;align-self:start;min-width:0;height:calc(4.44em + 9px);margin:0;padding-top:8px;overflow:hidden;border-top:1px solid #cfd9dd;color:#4e5e67;font-size:13px;line-height:1.48;line-clamp:3;-webkit-box-orient:vertical;-webkit-line-clamp:3}
    .empty{color:#7c8991}
    .weather-section{margin-top:20px}.weather-heading{display:flex;justify-content:space-between;align-items:end;border-bottom:1px solid #9eb0bb}.weather-heading h2{margin:0;border:0}.weather-heading small{padding-bottom:6px;color:var(--muted);font-size:10px}
    .weather-forecasts{display:grid;gap:4px;margin-top:5px}.weather-forecast{display:grid;grid-template-columns:62px minmax(0,1fr);gap:8px;align-items:center;padding:6px 9px;border-left:4px solid var(--teal);background:#f4f8fa}.weather-forecast.weather-폭우{border-left-color:var(--red);background:#fdf4f4}.weather-forecast.weather-폭염{border-left-color:var(--amber);background:#fff8e9}.weather-forecast>strong{color:var(--navy);font-size:var(--copy-size);line-height:1.45}.weather-forecast>p{display:flex;flex-wrap:wrap;gap:2px 14px;margin:0;font-size:var(--copy-size);line-height:1.45}.weather-forecast>p b{color:var(--navy)}.weather-forecast>p span{color:#6f3030;font-weight:600}
    @media screen and (max-width:760px){main{width:calc(100% - 16px)}.report-page{width:100%;height:auto;min-height:0;padding:20px;overflow:visible}.page-inner{width:100%;transform:none}.masthead .top{display:block}.date{text-align:left;margin-top:12px}.weather-forecast{grid-template-columns:1fr;gap:2px}.articles,.articles.is-twelve{grid-template-columns:1fr;grid-template-rows:none;height:auto}.article{min-height:112px}.appendix-title{grid-template-columns:auto auto}.appendix-count{grid-column:1/-1;justify-self:start;margin-top:7px}}
    @page{size:A4;margin:0}
    @media print{body{background:#fff}.toolbar{display:none}main{width:210mm;margin:0;display:block}.report-page{height:294mm;box-shadow:none;break-after:page;page-break-after:always}.report-page:last-child{break-after:auto;page-break-after:auto}a{text-decoration:none;color:inherit}.article-link,.issue-rep a{color:var(--navy)}}
    """
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light"><title>KESCO CEO 언론브리핑 { _text(report_date) }</title><style>{styles}</style></head><body>
    <div class="toolbar"><a href="/">편집 화면</a><button id="articleSortBtn" type="button" aria-pressed="false" onclick="toggleArticleSort()">기사 중요도순</button><button type="button" onclick="window.print()">인쇄·PDF</button></div>
    <main>
    <section class="report-page analysis-page" data-fit-page><div class="page-inner">
    <header class="masthead">
    <div class="doc-meta"><span>한국전기안전공사</span><span>대외 언론동향 · CEO 보고</span></div>
    <div class="top"><div><p class="eyebrow">CEO MEDIA INTELLIGENCE</p><h1>일일 언론 동향 보고</h1><p class="subtitle">CEO 핵심 브리핑 · 관련 기사 별첨</p><span class="status {badge_class}">{_text(badge)}</span></div>
    <div class="date"><strong>{_text(date_label)}</strong><small>{('작성 ' + _text(briefing.get('preparedBy'))) if briefing.get('preparedBy') else '작성자 미지정'}</small></div></div>
    </header>
    <div class="body">
    <section class="section"><h2>① 오늘 한줄</h2>{_render_lead(analysis.get('managementMessage'))}</section>
    <section class="section trend-section"><h2>② 언론 동향 분석</h2>{_render_trend_analysis(analysis)}</section>
    <section class="section"><h2>③ 경영 참고사항</h2>{_render_management_reference(analysis)}</section>
    {f'<section class="section"><h2>④ 기타 동향</h2>{monitoring_reference}</section>' if (monitoring_reference := _render_monitoring_reference(analysis)) else ''}
    {weather_html}
    </div></div></section>
    <section class="report-page articles-page" data-fit-page><div class="page-inner">
    <header class="appendix-masthead" id="appendix-articles"><div class="doc-meta"><span>한국전기안전공사</span><span>대외 언론동향 · CEO 보고</span></div><div class="appendix-title"><p class="eyebrow">RELATED NEWS</p><h2>관련기사</h2><div class="appendix-count"><strong>{article_count}</strong><span>BRIEFING<br>ARTICLES</span></div></div></header>
    <div class="articles{article_layout_class}">{_article_cards(snapshot)}</div>
    </div></section></main><script>
    function toggleArticleSort() {{
      const list = document.querySelector('.articles');
      const button = document.getElementById('articleSortBtn');
      if (!list || !button) return;
      const importanceMode = button.getAttribute('aria-pressed') !== 'true';
      const cards = Array.from(list.querySelectorAll('.article'));
      cards.sort((left, right) => importanceMode
        ? Number(right.dataset.starred) - Number(left.dataset.starred)
          || Number(left.dataset.riskRank) - Number(right.dataset.riskRank)
          || Number(right.dataset.priorityScore) - Number(left.dataset.priorityScore)
          || Number(left.dataset.editorIndex) - Number(right.dataset.editorIndex)
        : Number(left.dataset.editorIndex) - Number(right.dataset.editorIndex));
      cards.forEach((card, index) => {{
        const number = card.querySelector('.article-number');
        if (number) number.textContent = String(index + 1).padStart(2, '0');
        list.appendChild(card);
      }});
      button.setAttribute('aria-pressed', String(importanceMode));
      button.textContent = importanceMode ? '기사 편집순' : '기사 중요도순';
    }}
    </script></body></html>"""
