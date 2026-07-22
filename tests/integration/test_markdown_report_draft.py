from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.services.extraction.article_body import BodyFetchResult
from backend.app.services.reports.renderer import _analysis_for_display

client = TestClient(app)


def _selected_article(report_date: str) -> str:
    client.put(
        f"/api/briefings/{report_date}",
        json={"expectedRevision": 0, "patch": {"preparedBy": "홍보실"}},
    )
    response = client.post(
        "/api/articles",
        json={
            "reportDate": report_date,
            "title": "전기안전 특별점검 확대",
            "source": "테스트일보",
            "url": f"https://example.com/report-draft/{report_date}",
            "description": "RSS 요약입니다.",
            "category": "kesco_achievement",
        },
    )
    article_id = response.json()["data"]["id"]
    briefing = client.get(f"/api/briefings/{report_date}").json()["data"]
    client.patch(
        f"/api/briefings/{report_date}/articles/{article_id}",
        json={
            "expectedRevision": briefing["revision"],
            "selected": True,
            "starred": True,
            "topIssue": True,
            "note": "CEO 확인 필요",
        },
    )
    return article_id


def _analysis(evidence_id: str = "A01") -> dict:
    return {
        "managementMessage": {"text": "외부 AI 경영메시지", "articleIds": [evidence_id]},
        "situationSummary": {"text": "외부 AI 언론상황", "articleIds": [evidence_id]},
        "keyIssues": [],
        "decisionPoints": [{"text": "현장 대응 확인", "articleIds": [evidence_id]}],
        "actionItems": [],
        "riskOutlook": {
            "text": "후속 보도 가능성",
            "articleIds": [evidence_id],
            "isInference": True,
        },
        "limitations": [],
        "confidence": "high",
    }


def test_legacy_single_field_external_analysis_is_split_for_display_only():
    legacy = _analysis()
    legacy["managementMessage"]["text"] = (
        "1. 언론 동향 시사점\n우선 점검합니다.\n\n"
        "2. 언론 동향 분석\n현장 흐름을 분석합니다.\n\n"
        "3. 경영 참고사항\n내부 체계를 살펴봅니다."
    )
    legacy["situationSummary"] = {"text": "", "articleIds": []}
    legacy["decisionPoints"] = []
    legacy["riskOutlook"] = {"text": "", "articleIds": [], "isInference": True}

    displayed = _analysis_for_display(legacy)

    assert displayed["managementMessage"]["text"] == "우선 점검합니다."
    assert displayed["situationSummary"]["text"] == "현장 흐름을 분석합니다."
    assert displayed["actionItems"][0]["action"] == "내부 체계를 살펴봅니다."
    assert legacy["managementMessage"]["text"].startswith("1. 언론 동향 시사점")


def test_new_plain_text_no_reference_phrase_does_not_create_reference_issue():
    from backend.app.services.reports.report_draft import content_from_plain_text

    content = content_from_plain_text(
        "① 오늘의 핵심\n현안을 확인합니다.\n\n"
        "② 경영 시사점\n업무 범위를 검토합니다.\n\n"
        "④ 기타 동향\n별도 기타 동향 없음.",
        ["A01"],
    )

    assert content["keyIssues"] == []


def test_new_plain_text_splits_management_and_optional_monitoring_sections():
    from backend.app.services.reports.report_draft import content_from_plain_text

    content = content_from_plain_text(
        "① 오늘 한줄\n현안을 확인합니다.\n\n"
        "② 언론 동향 분석\n공식 조사 결과를 기다립니다.\n\n"
        "③ 경영 참고사항\n관계기관과 전기적 요인을 확인합니다.\n\n"
        "④ 기타 동향\n그리드코드 개정 동향을 모니터링합니다.",
        ["A01"],
    )

    assert content["actionItems"][0]["action"] == "관계기관과 전기적 요인을 확인합니다."
    assert content["keyIssues"][0]["summary"] == "그리드코드 개정 동향을 모니터링합니다."


def test_markdown_export_contains_selected_full_text_tags_and_template(monkeypatch):
    report_date = "2098-07-20"
    _selected_article(report_date)
    full_text = "외부 고성능 AI에 전달할 기사 전문입니다. " * 30
    monkeypatch.setattr(
        "backend.app.services.extraction.article_body.fetch_article_body",
        lambda url: BodyFetchResult(full_text, "full_text"),
    )

    response = client.post(f"/api/exports/{report_date}.md")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert "[A01] 전기안전 특별점검 확대" in response.text
    assert full_text.strip() in response.text
    assert "중요 표시: 예" in response.text
    assert "Top Issue: 예" in response.text
    assert "담당자 메모: CEO 확인 필요" in response.text
    assert "이 문서는 AI 분석의 근거 데이터다." in response.text
    assert "입력 서명:" in response.text
    assert "분석 적격 기사: 1건" in response.text
    assert "정제된 기사 본문 또는 유효 RSS 요약" in response.text
    assert response.headers["x-kesco-input-signature"]
    assert response.headers["x-kesco-file-hash"]


def test_external_analysis_is_validated_saved_and_used_by_preview():
    report_date = "2098-07-21"
    _selected_article(report_date)
    exchange = client.get(f"/api/briefings/{report_date}/report-draft").json()["data"]
    payload = {
        "reportDate": report_date,
        "inputSignature": exchange["inputSignature"],
        "sourceLabel": "고성능 AI",
        "text": (
            "① 오늘의 핵심\n외부 AI 경영메시지\n\n"
            "② 경영 시사점\n외부 AI 언론상황\n\n"
            "③ 참고 동향\n현장 대응 확인"
        ),
    }

    validated = client.post(
        f"/api/briefings/{report_date}/report-draft/validate", json=payload
    )
    assert validated.status_code == 200
    briefing = client.get(f"/api/briefings/{report_date}").json()["data"]
    saved = client.put(
        f"/api/briefings/{report_date}/report-draft",
        json={
            "expectedRevision": briefing["revision"],
            "sourceType": "external",
            "sourceLabel": "고성능 AI",
            "inputSignature": exchange["inputSignature"],
            "content": validated.json()["data"]["content"],
        },
    )
    assert saved.status_code == 200
    assert saved.json()["data"]["draft"]["sourceType"] == "external"

    preview = client.get(f"/preview/{report_date}")
    assert preview.status_code == 200
    assert "외부 AI 경영메시지" in preview.text
    assert "외부 AI 언론상황" in preview.text
    assert "오늘 한줄" in preview.text
    assert "언론 동향 분석" in preview.text
    assert "경영 참고사항" in preview.text
    assert "기타 동향" in preview.text
    assert "참고 동향" not in preview.text
    assert "관련기사" in preview.text
    assert "분석 근거" not in preview.text
    assert "근거 기사 링크" not in preview.text
    assert "RSS 요약입니다." in preview.text
    assert "고성능 AI" not in preview.text
    assert "CEO 보고 편집본" not in preview.text
    assert "CEO 참고·지시사항" not in preview.text
    assert 'class="evidence-list"' not in preview.text

    exported = client.get(f"/api/exports/{report_date}.json").json()["data"]
    assert exported["reportDraft"]["content"]["managementMessage"]["text"] == "외부 AI 경영메시지"
    assert exported["reportDraft"]["content"]["situationSummary"]["text"] == "외부 AI 언론상황"
    assert exported["reportDraft"]["content"]["keyIssues"][0]["summary"] == "현장 대응 확인"

    current = client.get(f"/api/briefings/{report_date}").json()["data"]
    finalized = client.post(
        f"/api/briefings/{report_date}/finalize",
        json={"expectedRevision": current["revision"]},
    )
    assert finalized.status_code == 200
    version = client.get(f"/api/briefings/{report_date}/versions/1").json()["data"]
    assert version["snapshot"]["reportDraft"]["sourceLabel"] == "고성능 AI"

    restored_date = "2098-07-23"
    restored = client.post(f"/api/exports/{restored_date}.json", json=exported)
    assert restored.status_code == 200
    restored_draft = client.get(
        f"/api/briefings/{restored_date}/report-draft"
    ).json()["data"]["draft"]
    assert restored_draft["content"]["managementMessage"]["text"] == "외부 AI 경영메시지"


def test_external_analysis_rejects_unknown_evidence_id():
    report_date = "2098-07-22"
    _selected_article(report_date)
    exchange = client.get(f"/api/briefings/{report_date}/report-draft").json()["data"]
    response = client.post(
        f"/api/briefings/{report_date}/report-draft/validate",
        json={"inputSignature": exchange["inputSignature"], "analysis": _analysis("A99")},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "REPORT_DRAFT_INVALID"


def test_generated_markdown_signature_and_evidence_drive_external_draft(monkeypatch):
    report_date = "2098-07-24"
    article_id = _selected_article(report_date)
    full_text = "공사는 전기설비 현장 안전점검 결과와 후속 조치 일정을 공식 발표했다. " * 30
    monkeypatch.setattr(
        "backend.app.services.extraction.article_body.fetch_article_body",
        lambda url: BodyFetchResult(full_text, "full_text"),
    )

    markdown = client.post(f"/api/exports/{report_date}.md")
    assert markdown.status_code == 200
    signature = markdown.headers["x-kesco-input-signature"]
    exchange = client.get(f"/api/briefings/{report_date}/report-draft").json()["data"]
    assert exchange["inputSignature"] == signature
    assert exchange["evidence"] == {"A01": article_id}

    validated = client.post(
        f"/api/briefings/{report_date}/report-draft/validate",
        json={
            "reportDate": report_date,
            "inputSignature": signature,
            "text": "① 오늘의 핵심\n현장 안전점검 결과를 확인했습니다.",
        },
    )
    assert validated.status_code == 200
    briefing = client.get(f"/api/briefings/{report_date}").json()["data"]
    saved = client.put(
        f"/api/briefings/{report_date}/report-draft",
        json={
            "expectedRevision": briefing["revision"],
            "sourceType": "external",
            "sourceLabel": "외부 AI",
            "inputSignature": signature,
            "content": validated.json()["data"]["content"],
        },
    )
    assert saved.status_code == 200

    current = client.get(f"/api/briefings/{report_date}").json()["data"]
    changed = client.patch(
        f"/api/briefings/{report_date}/articles/{article_id}",
        json={"expectedRevision": current["revision"], "note": "Markdown 생성 후 변경"},
    )
    assert changed.status_code == 200
    stale = client.get(f"/api/briefings/{report_date}/report-draft").json()["data"]
    assert stale["inputSignature"] != signature
    assert stale["draft"]["stale"] is True
