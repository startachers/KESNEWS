from __future__ import annotations

from datetime import date
from html import escape
from typing import Any


def _text(value: Any, fallback: str = "") -> str:
    return escape(str(value if value not in (None, "") else fallback))


def _claim(value: Any) -> tuple[str, list[str]]:
    if not isinstance(value, dict):
        return "", []
    return str(value.get("text") or ""), list(value.get("articleIds") or [])


def _evidence_links(ids: list[str], evidence: dict[str, Any]) -> str:
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


def _render_ai_analysis(analysis: dict[str, Any], evidence: dict[str, Any]) -> str:
    sections = [
        _render_claim("경영 메시지", analysis.get("managementMessage"), evidence),
        _render_claim("언론 상황", analysis.get("situationSummary"), evidence),
    ]
    for item in analysis.get("keyIssues") or []:
        text = " · ".join(
            part
            for part in (
                item.get("title"),
                item.get("summary"),
                f"경영 영향: {item.get('managementImpact')}" if item.get("managementImpact") else "",
            )
            if part
        )
        sections.append(
            _render_claim(
                "AI 핵심 이슈",
                {"text": text, "articleIds": item.get("articleIds") or []},
                evidence,
            )
        )
    for item in analysis.get("decisionPoints") or []:
        sections.append(_render_claim("경영 판단 포인트", item, evidence))
    for item in analysis.get("actionItems") or []:
        text = f"[{item.get('priority', '확인')}] {item.get('action', '')}".strip()
        sections.append(
            _render_claim(
                "AI 확인·지시 제안",
                {"text": text, "articleIds": item.get("articleIds") or []},
                evidence,
            )
        )
    if analysis.get("riskOutlook"):
        sections.append(_render_claim("위험 전망(추론)", analysis["riskOutlook"], evidence))
    return "".join(sections)


def _issue_cards(snapshot: dict[str, Any]) -> str:
    issues = snapshot.get("issues") or []
    if issues:
        priority = {"required": 0, "review": 1, "reference": 2}
        ordered = sorted(
            issues,
            key=lambda item: (
                priority.get(item.get("effectivePriority"), 9),
                -(item.get("autoPriorityScore") or 0),
                item.get("id") or "",
            ),
        )[:3]
        return "".join(
            f'<article class="issue"><span>ISSUE {index:02d}</span>'
            f'<h3>{_text(item.get("effectiveTitle"), "제목 없음")}</h3>'
            f'<p>{_text(item.get("effectiveStatus"), "상태 미지정")} · '
            f'{_text(item.get("effectivePriority"), "reference")}</p></article>'
            for index, item in enumerate(ordered, 1)
        )
    articles = snapshot.get("articles") or []
    return "".join(
        f'<article class="issue"><span>ISSUE {index:02d}</span><h3>{_text(item.get("title"))}</h3>'
        f'<p>{_text(item.get("source"), "출처 미상")}</p></article>'
        for index, item in enumerate(articles[:3], 1)
    ) or '<p class="empty">선정된 핵심 이슈가 없습니다.</p>'


def _article_cards(
    snapshot: dict[str, Any], *, direct_only: bool = False, include_anchors: bool = True
) -> str:
    articles = snapshot.get("articles") or []
    if direct_only:
        articles = [item for item in articles if item.get("category") == "direct"]
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
        cards.append(
            f'<article class="article"{anchor}>'
            f'<span class="number">{index:02d}</span><div><h3>{title_html}</h3>'
            f'<p class="meta">{_text(item.get("source"), "출처 미상")} · '
            f'{_text(item.get("pubDate"), "시각 미상")} · {_text(item.get("priority") or item.get("risk"))}</p>'
            f'<p>{_text(item.get("description"))}</p>{note}</div></article>'
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
        '<section class="section"><h2>AI 근거 기사</h2>'
        '<p class="empty">분석 이후 선정 상태가 바뀌었지만 최종본의 근거 연결을 위해 보존한 기사입니다.</p>'
        f'<div class="articles">{_article_cards(temporary)}</div></section>'
    )


def render_report(snapshot: dict[str, Any], *, preview: bool = False) -> str:
    briefing = snapshot.get("briefing") or {}
    report_date = str(snapshot.get("reportDate") or "")
    try:
        date_label = date.fromisoformat(report_date).strftime("%Y. %m. %d")
    except ValueError:
        date_label = report_date
    version = snapshot.get("version")
    badge = "작업본 미리보기" if preview else f"최종본 v{version}"
    ai_run = snapshot.get("aiRun") or {}
    analysis = ((ai_run.get("response") or {}).get("analysis") or {})
    evidence = snapshot.get("evidence") or {}
    ai_html = _render_ai_analysis(analysis, evidence)
    summary = briefing.get("situationSummary") or "작성된 종합상황이 없습니다."
    action_note = briefing.get("actionNote") or "별도 지시사항 없음"
    stale_notice = (
        '<p class="warning">주의: AI 분석 이후 선정 기사·메모·이슈 연결이 변경된 상태에서 확정됐습니다.</p>'
        if ai_run.get("stale")
        else ""
    )
    styles = """
    :root{color-scheme:light;--navy:#10253c;--teal:#087f76;--line:#dce3e5;--soft:#f4f7f7}
    *{box-sizing:border-box}body{margin:0;background:#edf1f2;color:#263641;font-family:-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Noto Sans KR",sans-serif;line-height:1.6}
    .toolbar{position:sticky;top:0;z-index:2;display:flex;justify-content:flex-end;gap:8px;padding:10px 20px;background:#10253cee}.toolbar a,.toolbar button{border:1px solid #ffffff55;border-radius:8px;padding:7px 12px;background:#fff;color:var(--navy);font-weight:700;text-decoration:none;cursor:pointer}
    main{width:min(980px,calc(100% - 28px));margin:24px auto;background:#fff;box-shadow:0 14px 45px #10253c18}.masthead{padding:40px 46px;background:linear-gradient(135deg,#10253c,#183c56);color:#fff}.masthead .top{display:flex;justify-content:space-between;gap:20px}.eyebrow{margin:0;color:#77d2c9;font-size:11px;letter-spacing:.16em;text-transform:uppercase}.masthead h1{margin:6px 0 0;font-size:34px}.date{font-size:24px;font-weight:800;text-align:right}.date small{display:block;color:#c1d0db;font-size:11px}.body{padding:30px 42px 44px}.status{display:inline-block;margin-bottom:20px;border-radius:999px;padding:5px 10px;background:#e3f3f0;color:#086b63;font-size:11px;font-weight:800}.section{margin-top:28px}.section h2{margin:0 0 12px;padding-bottom:8px;border-bottom:2px solid var(--navy);color:var(--navy);font-size:18px}.summary{padding:20px;border-left:4px solid var(--teal);background:var(--soft);white-space:pre-wrap}.issues{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.issue{min-height:130px;padding:16px;border:1px solid var(--line);border-radius:12px}.issue span,.number{color:var(--teal);font-size:10px;font-weight:800}.issue h3{margin:9px 0;font-size:14px}.issue p{margin:0;color:#6b7982;font-size:11px}.claim{padding:15px 17px;border:1px solid var(--line);border-radius:10px;margin-top:9px}.claim h3{margin:0;color:var(--navy);font-size:13px}.claim p{margin:6px 0}.evidence-list{font-size:10px;color:#71808a}.evidence{display:inline-block;margin-left:4px;padding:2px 6px;border-radius:999px;background:#e3f3f0;color:#086b63;text-decoration:none}.articles{display:grid;gap:9px}.article{display:grid;grid-template-columns:30px 1fr;gap:10px;padding:15px;border:1px solid var(--line);border-radius:10px;break-inside:avoid}.article h3{margin:0;font-size:14px}.article h3 a{color:var(--navy)}.article p{margin:6px 0 0;font-size:11px}.article .meta{color:#74828b;font-size:10px}.article .note{padding:6px 8px;background:#fff8e9;color:#6d5324}.action{padding:16px;background:#fff8e9;white-space:pre-wrap}.empty{color:#7c8991}.warning{padding:10px 12px;border-left:3px solid #c97a16;background:#fff4df;color:#72501f;font-size:11px}.footer{margin-top:32px;padding-top:12px;border-top:1px solid var(--line);color:#77858e;font-size:10px}
    @media(max-width:700px){.masthead,.body{padding:24px}.masthead .top{display:block}.date{text-align:left;margin-top:20px}.issues{grid-template-columns:1fr}}
    @page{size:A4;margin:12mm}@media print{body{background:#fff;font-size:10pt}.toolbar{display:none}main{width:auto;margin:0;box-shadow:none}.masthead{padding:12mm 10mm}.body{padding:8mm 6mm}.section{margin-top:7mm}.issues{gap:2mm}.issue{min-height:30mm;padding:3mm}.claim,.article{break-inside:avoid}.footer{font-size:7pt}}
    """
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light"><title>KESCO CEO 언론브리핑 { _text(report_date) }</title><style>{styles}</style></head><body>
    <div class="toolbar"><a href="/">편집 화면</a><button type="button" onclick="window.print()">인쇄·PDF</button></div>
    <main><header class="masthead"><div class="top"><div><p class="eyebrow">CEO Morning Intelligence</p><h1>일일 언론브리핑</h1></div><div class="date">{_text(date_label)}<small>{_text(briefing.get('preparedBy'), '작성자 미지정')}</small></div></div></header>
    <div class="body"><span class="status">{_text(badge)}</span>
    <section class="section"><h2>오늘의 언론상황</h2>{stale_notice}<div class="summary">{_text(summary)}</div>{ai_html}</section>
    <section class="section"><h2>핵심 이슈</h2><div class="issues">{_issue_cards(snapshot)}</div></section>
    <section class="section"><h2>확인·지시 필요사항</h2><div class="action">{_text(action_note)}</div></section>
    <section class="section"><h2>공사 직접 보도</h2><div class="articles">{_article_cards(snapshot, direct_only=True, include_anchors=False)}</div></section>
    <section class="section"><h2>선정 기사 별첨</h2><div class="articles">{_article_cards(snapshot)}</div></section>
    {_unselected_evidence_cards(snapshot)}
    <footer class="footer">최종본은 확정 당시 기사·평가·메모·AI 근거의 불변 snapshot입니다. · 확정시각 {_text(snapshot.get('finalizedAt'), '미확정')}</footer></div></main></body></html>"""
