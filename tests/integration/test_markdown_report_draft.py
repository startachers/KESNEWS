from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.services.extraction.article_body import BodyFetchResult

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


def test_markdown_export_contains_selected_full_text_tags_and_template(monkeypatch):
    report_date = "2098-07-20"
    _selected_article(report_date)
    full_text = "외부 고성능 AI에 전달할 기사 전문입니다. " * 20
    monkeypatch.setattr(
        "backend.app.services.extraction.article_body.fetch_article_body",
        lambda url: BodyFetchResult(full_text, "full_text"),
    )

    response = client.post(f"/api/exports/{report_date}.md")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert "[A01] 전기안전 특별점검 확대" in response.text
    assert full_text in response.text
    assert "중요 표시: 예" in response.text
    assert "Top Issue: 예" in response.text
    assert "담당자 메모: CEO 확인 필요" in response.text
    assert "JSON이나 코드 블록으로 출력하지 마십시오." in response.text
    assert "입력 서명:" in response.text


def test_external_analysis_is_validated_saved_and_used_by_preview():
    report_date = "2098-07-21"
    _selected_article(report_date)
    exchange = client.get(f"/api/briefings/{report_date}/report-draft").json()["data"]
    payload = {
        "reportDate": report_date,
        "inputSignature": exchange["inputSignature"],
        "sourceLabel": "고성능 AI",
        "text": "외부 AI 경영메시지\n\n외부 AI 언론상황",
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
    assert "고성능 AI" in preview.text

    exported = client.get(f"/api/exports/{report_date}.json").json()["data"]
    assert exported["reportDraft"]["content"]["managementMessage"]["text"] == payload["text"]

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
    assert restored_draft["content"]["managementMessage"]["text"] == payload["text"]


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
