from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from html import escape
from typing import Any

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


def _evidence_links(ids: list[str], evidence: dict[str, Any]) -> str:
    if len(ids) > 8:
        labels = ", ".join(_text(evidence_id) for evidence_id in ids)
        return (
            f'<a class="evidence evidence-all" href="#appendix-articles" '
            f'title="{labels}">선정 기사 전체 {len(ids)}건</a>'
        )
    links = []
    for evidence_id in ids:
        item = evidence.get(evidence_id) or {}
        article_id = item.get("articleId") or ""
        label = _text(evidence_id)
        if article_id:
            links.append(f'<a class="evidence" href="#article-{_text(article_id)}">{label}</a>')
        else:
            links.append(f'<span class="evidence missing">{label}</span>')
    return " ".join(links)


def _render_claim(title: str, value: Any, evidence: dict[str, Any]) -> str:
    text, ids = _claim(value)
    if not text:
        return ""
    return (
        f'<section class="claim"><h3>{_text(title)}</h3><p>{_text(text)}</p>'
        f'<div class="evidence-list">근거 {_evidence_links(ids, evidence)}</div></section>'
    )


def _render_lead(value: Any, evidence: dict[str, Any]) -> str:
    text, ids = _claim(value)
    if not text:
        return '<p class="empty">작성된 언론 동향 시사점이 없습니다.</p>'
    return (
        f'<div class="analysis-lead"><p>{_text(text)}</p>'
        f'<div class="evidence-list">분석 근거 {_evidence_links(ids, evidence)}</div></div>'
    )


def _render_trend_analysis(analysis: dict[str, Any], evidence: dict[str, Any]) -> str:
    sections = []
    situation = analysis.get("situationSummary")
    situation_text, situation_ids = _claim(situation)
    if situation_text:
        sections.append(
            f'<div class="analysis-prose"><p>{_text(situation_text)}</p>'
            f'<div class="evidence-list">분석 근거 '
            f'{_evidence_links(situation_ids, evidence)}</div></div>'
        )
    for item in analysis.get("keyIssues") or []:
        impact = (
            f'<p class="management-impact"><strong>경영 관점</strong> '
            f'{_text(item.get("managementImpact"))}</p>'
            if item.get("managementImpact")
            else ""
        )
        sections.append(
            f'<article class="analysis-issue"><h3>{_text(item.get("title"), "핵심 이슈")}</h3>'
            f'<p>{_text(item.get("summary"))}</p>{impact}'
            f'<div class="evidence-list">분석 근거 '
            f'{_evidence_links(item.get("articleIds") or [], evidence)}</div></article>'
        )
    outlook_text, outlook_ids = _claim(analysis.get("riskOutlook"))
    if outlook_text:
        sections.append(
            f'<aside class="outlook"><span>전망</span><p>{_text(outlook_text)}</p>'
            f'<div class="evidence-list">분석 근거 '
            f'{_evidence_links(outlook_ids, evidence)}</div></aside>'
        )
    return "".join(sections) or '<p class="empty">작성된 언론 동향 분석이 없습니다.</p>'


def _render_management_reference(analysis: dict[str, Any], evidence: dict[str, Any]) -> str:
    items = []
    for item in analysis.get("decisionPoints") or []:
        text, ids = _claim(item)
        if text:
            items.append(
                f'<li><p>{_text(text)}</p><div class="evidence-list">근거 '
                f'{_evidence_links(ids, evidence)}</div></li>'
            )
    for item in analysis.get("actionItems") or []:
        text = str(item.get("action") or "")
        if text:
            items.append(
                f'<li><p>{_text(text)}</p><div class="evidence-list">근거 '
                f'{_evidence_links(item.get("articleIds") or [], evidence)}</div></li>'
            )
    if not items:
        return '<p class="empty">별도 경영 참고사항이 없습니다.</p>'
    return f'<ol class="reference-list">{"".join(items)}</ol>'


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
        ("분석 근거", f"선정 기사 {len(articles)}건", ""),
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
    evidence_by_article: dict[str, str] | None = None,
) -> str:
    articles = snapshot.get("articles") or []
    if direct_only:
        articles = [item for item in articles if item.get("category") in DIRECT_CATEGORIES]
    if not articles:
        return '<p class="empty">해당 기사가 없습니다.</p>'
    cards = []
    for index, item in enumerate(articles, 1):
        url = str(item.get("url") or "")
        title = _text(item.get("title"), "제목 없음")
        title_html = (
            f'<a href="{_text(url)}" target="_blank" rel="noopener noreferrer">{title}</a>'
            if url.startswith(("http://", "https://"))
            else title
        )
        note = f'<p class="note">담당자 메모: {_text(item.get("note"))}</p>' if item.get("note") else ""
        anchor = f' id="article-{_text(item.get("id"))}"' if include_anchors else ""
        risk_class = " critical" if item.get("risk") == "critical" else ""
        evidence_id = (evidence_by_article or {}).get(str(item.get("id") or ""))
        evidence_label = f'<span class="article-evidence">{_text(evidence_id)}</span>' if evidence_id else f'<span class="number">{index:02d}</span>'
        description = " ".join(str(item.get("description") or "핵심 요약 없음").split())
        cards.append(
            f'<article class="article{risk_class}"{anchor}>'
            f'{evidence_label}<div class="article-main"><div class="article-title-row"><h3>{title_html}</h3>'
            f'<p class="meta">{_text(item.get("source"), "출처 미상")} · '
            f'{_text(_datetime_label(item.get("pubDate"), "시각 미상"))}</p></div>'
            f'<p class="desc"><span>핵심 1줄</span>{_text(description)}</p>{note}</div></article>'
        )
    return "".join(cards)


def _unselected_evidence_cards(snapshot: dict[str, Any]) -> str:
    selected_ids = {item.get("id") for item in snapshot.get("articles") or []}
    items = []
    for evidence_id, evidence in (snapshot.get("evidence") or {}).items():
        if evidence.get("articleId") in selected_ids:
            continue
        article = dict(evidence.get("article") or {})
        article["evidenceId"] = evidence_id
        items.append(article)
    if not items:
        return ""
    temporary = {"articles": items}
    return (
        '<section class="section appendix"><h2><span class="sec-tag">붙임 2</span>AI 근거 기사</h2>'
        '<p class="section-caption">분석 이후 선정 상태가 바뀌었지만 최종본의 근거 연결을 위해 보존한 기사입니다.</p>'
        f'<div class="articles">{_article_cards(temporary)}</div></section>'
    )


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
    evidence = snapshot.get("evidence") or {}
    has_analysis = bool(
        _claim(analysis.get("managementMessage"))[0]
        or _claim(analysis.get("situationSummary"))[0]
        or analysis.get("keyIssues")
        or analysis.get("decisionPoints")
        or analysis.get("actionItems")
    )
    if has_analysis:
        if report_draft:
            source_label = report_draft.get("sourceLabel") or {
                "gemma": "Gemma 분석 편집본",
                "external": "외부 AI 분석 편집본",
                "manual": "담당자 편집본",
            }.get(report_draft.get("sourceType"), "CEO 보고 편집본")
            ai_caption = (
                f'<p class="section-caption">CEO 보고 편집본 · {_text(source_label)} · '
                f'수정 {_text(_datetime_label(report_draft.get("updatedAt"), "시각 미상"))}</p>'
            )
        else:
            ai_caption = (
                f'<p class="section-caption">모델 {_text(ai_run.get("model"), "미상")} · '
                f'생성 {_text(_datetime_label(briefing.get("aiGeneratedAt"), "시각 미상"))} · '
                "AI가 생성한 참고 분석으로, 최종 판단은 근거 기사 확인 후 내려 주시기 바랍니다.</p>"
            )
    else:
        ai_caption = '<p class="section-caption">이 작업본에서는 AI 분석이 실행되지 않았습니다.</p>'
    action_note = briefing.get("actionNote") or "별도 지시사항 없음"
    evidence_by_article = {
        str(item.get("articleId")): evidence_id
        for evidence_id, item in evidence.items()
        if item.get("articleId")
    }
    stale_notice = (
        '<p class="warning">주의: AI 분석 이후 선정 기사·메모·이슈 연결이 변경된 상태에서 확정됐습니다.</p>'
        if (report_draft.get("stale") if report_draft else ai_run.get("stale"))
        else ""
    )
    styles = """
    :root{color-scheme:light;--navy:#12243a;--navy2:#173b51;--teal:#087f76;--mint:#dff3ef;--red:#b02a2a;--amber:#b06a12;--line:#d7dfe3;--soft:#f4f7f7;--ink:#22303a;--muted:#66757f}
    *{box-sizing:border-box}
    body{margin:0;background:#e8edef;color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Noto Sans KR",sans-serif;line-height:1.65;font-size:14px}
    .toolbar{position:sticky;top:0;z-index:2;display:flex;justify-content:flex-end;gap:8px;padding:10px 20px;background:#10253cee}
    .toolbar a,.toolbar button{border:1px solid #ffffff55;border-radius:8px;padding:7px 14px;background:#fff;color:var(--navy);font-weight:700;font-size:13px;text-decoration:none;cursor:pointer}
    main{width:min(1040px,calc(100% - 28px));margin:24px auto 48px;background:#fff;box-shadow:0 14px 45px #10253c1c}
    .masthead{position:relative;overflow:hidden;padding:38px 52px 34px;background:linear-gradient(125deg,#0d2138 0%,#173e52 72%,#0b756e 150%);color:#fff}
    .masthead:after{content:"";position:absolute;right:-90px;bottom:-145px;width:340px;height:340px;border:1px solid #ffffff1f;border-radius:50%;box-shadow:0 0 0 55px #ffffff0a,0 0 0 110px #ffffff08}
    .doc-meta{display:flex;justify-content:space-between;padding-bottom:14px;margin-bottom:20px;border-bottom:1px solid #ffffff2e;font-size:12.5px;letter-spacing:.04em;color:#c7d5e0;font-weight:600}
    .masthead .top{display:flex;justify-content:space-between;align-items:flex-end;gap:20px}
    .eyebrow{margin:0;color:#7ed7ce;font-size:11.5px;letter-spacing:.2em;text-transform:uppercase;font-weight:800}
    .masthead h1{margin:8px 0 0;font-size:35px;letter-spacing:-.035em}
    .masthead .subtitle{margin:8px 0 0;color:#c7d8df;font-size:13px}
    .date{text-align:right}.date strong{display:block;font-size:24px;font-weight:800}
    .date small{display:block;margin-top:6px;color:#c1d0db;font-size:12px}
    .status{display:inline-block;border-radius:999px;padding:5px 12px;font-size:12px;font-weight:800;margin-top:12px}
    .status.preview{background:#fff1d6;color:#8a5a10}.status.final{background:#e3f3f0;color:#086b63}
    .kpis{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;margin:0;padding:0 52px;background:#dbe3e5;border-bottom:1px solid var(--line)}
    .kpi{padding:15px 18px 14px;border:0;background:#f7f9f9}
    .kpi small{display:block;color:var(--muted);font-size:11px;font-weight:700;letter-spacing:.03em}
    .kpi strong{display:block;margin-top:4px;font-size:17px;color:var(--navy);letter-spacing:-.01em}
    .kpi.alert{border-color:#e4b6b6;background:#fdf3f3}.kpi.alert strong{color:var(--red)}
    .kpi.warn strong{color:var(--amber)}.kpi.calm strong{color:var(--teal)}
    .body{padding:10px 52px 46px}
    .section{margin-top:40px}
    .section h2{display:flex;align-items:center;gap:12px;margin:0 0 16px;padding-bottom:11px;border-bottom:1px solid #aab8bf;color:var(--navy);font-size:20px;letter-spacing:-.025em}
    .sec-num{display:inline-grid;place-items:center;width:28px;height:28px;border-radius:50%;background:var(--navy);color:#fff;font-size:12px;font-weight:800}
    .sec-tag{border-radius:6px;padding:2px 8px;background:var(--navy);color:#fff;font-size:12px;font-weight:800}
    .section-caption{margin:-4px 0 12px;color:var(--muted);font-size:12.5px}
    .analysis-source{display:flex;justify-content:space-between;gap:14px;align-items:center;margin:26px 0 -14px;padding:11px 14px;border-radius:8px;background:#f4f7f7;color:var(--muted);font-size:12px}
    .analysis-lead{position:relative;padding:26px 28px;border:1px solid #badbd6;border-radius:4px 18px 18px 4px;background:linear-gradient(135deg,#effaf7,#f8fbfb);box-shadow:inset 5px 0 var(--teal)}
    .analysis-lead:before{content:"CEO VIEW";display:block;margin-bottom:10px;color:var(--teal);font-size:10px;font-weight:900;letter-spacing:.16em}
    .analysis-lead p{margin:0;white-space:pre-wrap;color:#172e3b;font-size:17px;font-weight:700;line-height:1.85;letter-spacing:-.018em}
    .analysis-prose{padding:2px 2px 6px}.analysis-prose>p{margin:0;white-space:pre-wrap;font-size:15px;line-height:1.95;color:#293943}
    .analysis-issue{margin-top:14px;padding:18px 20px;border:1px solid var(--line);border-radius:10px;background:#fff;break-inside:avoid}
    .analysis-issue h3{margin:0 0 7px;color:var(--navy);font-size:15px}.analysis-issue>p{margin:0;white-space:pre-wrap}
    .management-impact{margin-top:10px!important;padding:9px 12px;background:#f3f7f7;color:#42535d}.management-impact strong{color:var(--teal)}
    .outlook{margin-top:14px;padding:15px 18px;border-left:4px solid var(--amber);background:#fff8e9}.outlook>span{font-size:11px;font-weight:800;color:var(--amber)}.outlook>p{margin:4px 0;white-space:pre-wrap}
    .reference-list{margin:0;padding:0;list-style:none;counter-reset:reference}.reference-list li{position:relative;margin-top:10px;padding:17px 18px 15px 52px;border:1px solid var(--line);border-radius:10px;counter-increment:reference;break-inside:avoid}.reference-list li:before{content:counter(reference,decimal-leading-zero);position:absolute;left:17px;top:16px;color:var(--teal);font-weight:900}.reference-list p{margin:0;white-space:pre-wrap;font-size:14px}
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
    .claim{padding:15px 18px;border:1px solid var(--line);border-radius:10px;margin-top:10px;break-inside:avoid}
    .claim h3{margin:0;color:var(--navy);font-size:13.5px}.claim p{margin:7px 0;font-size:13.5px;white-space:pre-wrap}
    .evidence-list{margin-top:10px;font-size:10.5px;color:#71808a}
    .evidence{display:inline-block;margin-left:4px;padding:2px 7px;border-radius:999px;background:#e3f3f0;color:#086b63;text-decoration:none}.evidence-all{padding:3px 10px;font-weight:800}
    .articles{display:grid;gap:8px}
    .article{display:grid;grid-template-columns:42px 1fr;gap:10px;padding:13px 15px;border:1px solid var(--line);border-radius:8px;break-inside:avoid}
    .article.critical{border-color:#e4b6b6;border-left:4px solid var(--red);background:#fdf9f9}
    .article-title-row{display:flex;justify-content:space-between;align-items:baseline;gap:18px}.article h3{margin:0;font-size:14px;line-height:1.45}.article h3 a{color:var(--navy)}
    .article-evidence{display:grid;place-items:center;align-self:start;min-height:27px;border-radius:6px;background:var(--navy);color:#fff;font-size:11px;font-weight:900}
    .article .number{color:var(--teal);font-size:12px;font-weight:800}
    .article .meta{flex:0 0 auto;margin:0;color:#74828b;font-size:11px;white-space:nowrap}
    .article .badges{margin-top:7px;display:flex;flex-wrap:wrap;gap:4px}
    .article .desc{display:flex;gap:9px;margin:6px 0 0;font-size:12px;color:#42505a;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.article .desc span{flex:0 0 auto;color:var(--teal);font-size:10.5px;font-weight:800}
    .article .note{margin:8px 0 0;padding:7px 10px;border-radius:6px;background:#fff8e9;color:#6d5324;font-size:12.5px}
    .action{padding:18px 20px;border-left:4px solid var(--amber);background:#fff8e9;white-space:pre-wrap;font-size:14.5px}
    .empty{color:#7c8991}
    .warning{padding:10px 14px;border-left:3px solid #c97a16;background:#fff4df;color:#72501f;font-size:12.5px}
    .footer{margin-top:38px;padding-top:14px;border-top:1px solid var(--line);color:#77858e;font-size:11px;display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}
    @media(max-width:760px){.masthead,.body{padding-left:24px;padding-right:24px}.kpis{padding:0 24px;grid-template-columns:1fr}.masthead .top{display:block}.date{text-align:left;margin-top:16px}.article-title-row{display:block}.article .meta{margin-top:4px}.article .desc{white-space:normal}.analysis-lead p{font-size:15px}}
    @page{size:A4;margin:12mm}
    @media print{body{background:#fff;font-size:10pt}.toolbar{display:none}main{width:auto;margin:0;box-shadow:none}
    .masthead{padding:10mm 8mm 8mm}.masthead h1{font-size:22pt}.kpis{padding:0 8mm;gap:.3mm}.body{padding:0 8mm 8mm}
    .section{margin-top:7mm}.appendix{page-break-before:always;margin-top:0;padding-top:7mm}
    .issue,.claim,.article,.alert-box{break-inside:avoid}.footer{font-size:7pt}
    a{text-decoration:none;color:inherit}.article h3 a,.issue-rep a{color:var(--navy)}}
    """
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light"><title>KESCO CEO 언론브리핑 { _text(report_date) }</title><style>{styles}</style></head><body>
    <div class="toolbar"><a href="/">편집 화면</a><button type="button" onclick="window.print()">인쇄·PDF</button></div>
    <main>
    <header class="masthead">
    <div class="doc-meta"><span>한국전기안전공사</span><span>대외 언론동향 · CEO 보고</span></div>
    <div class="top"><div><p class="eyebrow">CEO MEDIA INTELLIGENCE</p><h1>일일 언론 동향 보고</h1><p class="subtitle">분석 중심 경영 브리핑 · 근거 기사 별첨</p><span class="status {badge_class}">{_text(badge)}</span></div>
    <div class="date"><strong>{_text(date_label)}</strong><small>{('작성 ' + _text(briefing.get('preparedBy'))) if briefing.get('preparedBy') else '작성자 미지정'}</small></div></div>
    </header>
    <div class="kpis">{_kpi_strip(snapshot)}</div>
    <div class="body">
    <div class="analysis-source">{stale_notice}{ai_caption}</div>
    <section class="section"><h2><span class="sec-num">01</span>언론 동향 시사점</h2>{_render_lead(analysis.get('managementMessage'), evidence)}</section>
    <section class="section"><h2><span class="sec-num">02</span>언론 동향 분석</h2>{_render_trend_analysis(analysis, evidence)}</section>
    <section class="section"><h2><span class="sec-num">03</span>경영 참고사항</h2>{_render_management_reference(analysis, evidence)}</section>
    <section class="section"><h2><span class="sec-num">04</span>CEO 참고·지시사항</h2><div class="action">{_text(action_note)}</div></section>
    <section class="section appendix" id="appendix-articles"><h2><span class="sec-tag">붙임</span>선정 기사 요약</h2><p class="section-caption">외부 AI 분석에 제공된 선정 기사입니다. 제목·핵심 1줄·언론사 정보로 빠르게 원문 근거를 확인할 수 있습니다.</p><div class="articles">{_article_cards(snapshot, evidence_by_article=evidence_by_article)}</div></section>
    {_unselected_evidence_cards(snapshot)}
    <footer class="footer"><span>최종본은 확정 당시 기사·평가·메모·AI 근거의 불변 snapshot입니다.</span><span>확정시각 {_text(_datetime_label(snapshot.get('finalizedAt'), '미확정', with_year=True))}</span></footer>
    </div></main></body></html>"""
