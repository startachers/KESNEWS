import json
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.services.reports.renderer import (
    _article_body_preview,
    _article_source_label,
    render_report,
)

client = TestClient(app)


def test_article_body_preview_removes_repeated_title_and_source_suffix():
    preview = _article_body_preview(
        {
            "title": "서울 아파트 화재…주민 대피 - 테스트일보",
            "source": "테스트일보",
            "bodyText": (
                "서울 아파트 화재…주민 대피 신고 20분 만에 초진됐다. "
                "소방당국은 정확한 원인을 조사하고 있다."
            ),
            "description": "RSS 요약입니다.",
        }
    )

    assert preview.startswith("신고 20분 만에 초진됐다.")
    assert not preview.startswith("서울 아파트 화재")


def test_article_source_label_uses_trusted_publisher_name_instead_of_domain():
    assert _article_source_label(
        {
            "source": "hani.co.kr",
            "url": "https://www.hani.co.kr/arti/society/environment/1210000.html",
        }
    ) == "한겨레"


def test_article_body_preview_falls_back_when_extracted_body_is_contaminated():
    preview = _article_body_preview(
        {
            "title": "[단독] ‘전력수요 급증’ 메가프로젝트…12차 전기본에 15GW 우선 반영할 듯",
            "source": "hani.co.kr",
            "bodyText": (
                "본문 사회 환경 [단독] ‘전력수요 급증’ 메가프로젝트…12차 전기본에 "
                "15GW 우선 반영할 듯 장수경 기자 수정 2026-07-21 19:32 펼침 0:00 "
                "Your browser does not support the audio element. 뉴스룸 PICK 다른 기사 어떠세요"
            ),
            "description": "정부가 발표한 3대 메가프로젝트로 신규 전력 수요가 늘어날 전망이다.",
        }
    )

    assert preview == "정부가 발표한 3대 메가프로젝트로 신규 전력 수요가 늘어날 전망이다."
    assert "Your browser" not in preview


def _create_selected_article(report_date: str) -> str:
    created = client.put(
        f"/api/briefings/{report_date}",
        json={"expectedRevision": 0, "patch": {"preparedBy": "홍보실", "actionNote": "1차 지시"}},
    )
    assert created.status_code == 200
    article = client.post(
        "/api/articles",
        json={
            "reportDate": report_date,
            "title": f"{report_date} 한국전기안전공사 안전점검 보도",
            "source": "테스트일보",
            "url": f"https://example.com/report/{report_date}",
            "description": "전기안전 취약시설 점검을 확대했다.",
            "category": "direct",
        },
    )
    assert article.status_code == 200
    return article.json()["data"]["id"]


def test_finalize_reopen_and_second_version_are_immutable():
    report_date = "2026-09-01"
    article_id = _create_selected_article(report_date)
    before = client.get(f"/api/briefings/{report_date}").json()["data"]

    first = client.post(
        f"/api/briefings/{report_date}/finalize",
        json={"expectedRevision": before["revision"]},
    )
    assert first.status_code == 200
    first_data = first.json()["data"]
    assert first_data["version"] == 1
    assert first_data["briefing"]["status"] == "final"
    assert Path(first_data["reportHtmlPath"]).is_file()

    locked = client.put(
        f"/api/briefings/{report_date}",
        json={"expectedRevision": first_data["briefing"]["revision"], "patch": {"actionNote": "변경"}},
    )
    assert locked.status_code == 409
    assert locked.json()["error"]["code"] == "BRIEFING_FINALIZED"
    manual = client.post(
        "/api/articles",
        json={"reportDate": report_date, "title": "잠금 뒤 기사", "source": "테스트"},
    )
    assert manual.status_code == 409

    reopened = client.post(
        f"/api/briefings/{report_date}/reopen",
        json={"expectedRevision": first_data["briefing"]["revision"]},
    )
    assert reopened.status_code == 200
    reopened_data = reopened.json()["data"]
    assert reopened_data["status"] == "draft"

    changed = client.put(
        f"/api/briefings/{report_date}",
        json={"expectedRevision": reopened_data["revision"], "patch": {"actionNote": "2차 지시"}},
    ).json()["data"]
    second = client.post(
        f"/api/briefings/{report_date}/finalize",
        json={"expectedRevision": changed["revision"]},
    )
    assert second.status_code == 200
    assert second.json()["data"]["version"] == 2

    versions = client.get(f"/api/briefings/{report_date}/versions").json()["data"]["versions"]
    assert [item["version"] for item in versions] == [2, 1]
    v1 = client.get(f"/api/briefings/{report_date}/versions/1").json()["data"]["snapshot"]
    v2 = client.get(f"/api/briefings/{report_date}/versions/2").json()["data"]["snapshot"]
    assert v1["briefing"]["actionNote"] == "1차 지시"
    assert v2["briefing"]["actionNote"] == "2차 지시"
    assert v1["articles"][0]["id"] == article_id


def test_preview_and_report_routes_are_read_only_and_versioned():
    report_date = "2026-09-02"
    _create_selected_article(report_date)
    preview = client.get(f"/preview/{report_date}")
    assert preview.status_code == 200
    assert "작업본 미리보기" in preview.text
    assert "AI 분석 이후 선정 기사·메모·이슈 연결이 변경된 상태" not in preview.text
    assert "textarea" not in preview.text
    assert preview.text.count('<section class="report-page') == 2
    assert preview.text.count(" data-fit-page>") == 2
    assert "padding:12mm 7mm" in preview.text
    assert "--report-scale:.93" in preview.text
    assert "--copy-size:14px" in preview.text
    assert 'content:"CEO VIEW"' not in preview.text
    assert ".analysis-lead p{margin:0;white-space:pre-wrap;color:#172e3b;font-size:15.4px;font-weight:700" in preview.text
    assert ".trend-section .analysis-prose>p" not in preview.text
    assert ".page-inner{width:100%;transform:scale(var(--report-scale));transform-origin:top center}" in preview.text
    assert "-webkit-print-color-adjust:exact;print-color-adjust:exact" in preview.text
    assert "@media screen and (max-width:760px)" in preview.text
    assert "const fitAll" not in preview.text
    assert "zoom:.68" not in preview.text
    assert "grid-template-columns:repeat(2,minmax(0,1fr))" in preview.text
    assert '<a class="article-link" href="https://example.com/report/2026-09-02"' in preview.text
    assert '<div class="article-main"><div class="article-title-row"><h3>' in preview.text
    assert '</p></div><p class="desc">' in preview.text
    assert "전기안전 취약시설 점검을 확대했다." in preview.text
    assert '.article-link{display:block;height:100%;min-width:0;color:inherit;text-decoration:none}' in preview.text
    assert ".article h3{display:-webkit-box;min-width:0;height:2.76em;min-height:2.76em" in preview.text
    assert "font-size:14.8px;line-height:1.38;letter-spacing:-.02em;line-clamp:2" in preview.text
    assert ".article .desc{display:-webkit-box;align-self:start;min-width:0;height:calc(4.44em + 9px)" in preview.text
    assert "제목과 핵심 요약을 각각 한 줄로 정리했습니다." not in preview.text
    assert '<button id="articleSortBtn" type="button" aria-pressed="false"' in preview.text
    assert "기사 중요도순" in preview.text
    assert 'class="appendix-masthead" id="appendix-articles"' in preview.text
    assert 'padding:13px 20px 14px;border-top:5px solid #35b8aa' in preview.text
    assert 'grid-template-columns:auto auto 1fr' in preview.text
    assert '.appendix-title h2{margin:0;color:#fff;font-size:24px' in preview.text
    assert 'grid-template-columns:repeat(2,minmax(0,1fr))' in preview.text
    assert '<span class="article-number" aria-hidden="true">01</span>' in preview.text
    assert '<div class="appendix-count"><strong>1</strong>' in preview.text
    assert '최종본은 확정 당시 기사·평가·메모·AI 분석을 보존합니다.' not in preview.text
    assert '확정시각' not in preview.text
    assert '<footer class="footer">' not in preview.text
    assert "<h2>관련기사</h2>" in preview.text
    assert "data-editor-index=\"0\"" in preview.text
    assert "data-starred=\"0\"" in preview.text
    assert "data-risk-rank=\"" in preview.text
    assert "Number(right.dataset.starred) - Number(left.dataset.starred)" in preview.text
    assert "Number(left.dataset.riskRank) - Number(right.dataset.riskRank)" in preview.text
    assert "Number(right.dataset.priorityScore) - Number(left.dataset.priorityScore)" in preview.text
    assert '<div class="kpis">' not in preview.text
    assert "number.textContent = String(index + 1).padStart(2, '0')" in preview.text

    assert client.get(f"/report/{report_date}").status_code == 404
    briefing = client.get(f"/api/briefings/{report_date}").json()["data"]
    client.post(
        f"/api/briefings/{report_date}/finalize",
        json={"expectedRevision": briefing["revision"]},
    )
    latest = client.get(f"/report/{report_date}")
    specified = client.get(f"/report/{report_date}?version=1")
    assert latest.status_code == specified.status_code == 200
    assert "최종본 v1" in latest.text
    assert "onclick=\"window.print()\"" in latest.text
    missing = client.get(f"/api/briefings/{report_date}/versions/99")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "BRIEFING_VERSION_NOT_FOUND"


def test_preview_rebuild_excludes_article_deselected_after_previous_preview():
    report_date = "2026-09-20"
    article_id = _create_selected_article(report_date)
    article_anchor = f'id="article-{article_id}"'

    first_preview = client.get(f"/preview/{report_date}")
    assert first_preview.status_code == 200
    assert article_anchor in first_preview.text

    briefing = client.get(f"/api/briefings/{report_date}").json()["data"]
    deselected = client.patch(
        f"/api/briefings/{report_date}/articles/{article_id}",
        json={"expectedRevision": briefing["revision"], "selected": False},
    )
    assert deselected.status_code == 200

    refreshed_preview = client.get(f"/preview/{report_date}")
    assert refreshed_preview.status_code == 200
    assert article_anchor not in refreshed_preview.text


def test_preview_appendix_does_not_restore_unselected_ai_evidence():
    selected_article = {
        "id": "selected-article",
        "title": "현재 브리핑 선정 기사",
        "source": "테스트일보",
        "description": "현재 선택 상태를 유지해야 한다.",
    }
    unselected_evidence = {
        "id": "unselected-evidence",
        "title": "과거 AI 근거지만 선택 해제한 기사",
        "source": "과거일보",
        "description": "분석 이후 선택에서 해제됐다.",
    }
    snapshot = {
        "reportDate": "2026-09-21",
        "version": None,
        "briefing": {},
        "articles": [selected_article],
        "evidence": {
            "A01": {"articleId": selected_article["id"], "article": selected_article},
            "A02": {
                "articleId": unselected_evidence["id"],
                "article": unselected_evidence,
            },
        },
    }

    preview = render_report(snapshot, preview=True)

    assert preview.count('<article class="article') == 1
    assert "현재 브리핑 선정 기사" in preview
    assert "과거 AI 근거지만 선택 해제한 기사" not in preview


def test_twelve_article_preview_uses_balanced_two_column_layout():
    articles = [
        {
            "id": f"article-{index:02d}",
            "title": f"브리핑 기사 {index:02d}",
            "source": "테스트일보",
            "description": "CEO 브리핑용 핵심 요약",
            "bodyText": f"추출된 기사 본문 {index:02d} 첫 문장과 후속 설명",
        }
        for index in range(1, 13)
    ]
    preview = render_report(
        {
            "reportDate": "2026-09-22",
            "version": None,
            "briefing": {},
            "articles": articles,
        },
        preview=True,
    )

    assert preview.count('<article class="article') == 12
    assert '<div class="articles is-twelve">' in preview
    assert '<div class="appendix-count"><strong>12</strong>' in preview
    assert "grid-template-rows:repeat(6,minmax(0,1fr))" in preview
    assert "height:264mm" in preview
    assert preview.count('class="article-number"') == 12
    assert "grid-template-rows:64px minmax(0,1fr)" in preview
    assert "추출된 기사 본문 01 첫 문장과 후속 설명" in preview
    assert "CEO 브리핑용 핵심 요약" not in preview
    assert "height:calc(4.44em + 9px)" in preview
    assert "font-size:13px;line-height:1.48;line-clamp:3" in preview
    assert "-webkit-line-clamp:3" in preview
    assert ".article.critical" not in preview


def test_final_snapshot_preserves_ai_evidence_article_link():
    report_date = "2026-09-03"
    article_id = _create_selected_article(report_date)
    analysis = {
        "managementMessage": {"text": "안전점검 보도를 확인해야 한다.", "articleIds": ["A01"]},
        "situationSummary": {"text": "직접 보도가 확인됐다.", "articleIds": ["A01"]},
        "keyIssues": [{"title": "안전점검", "urgency": "review", "summary": "직접 보도", "managementImpact": "후속 확인", "articleIds": ["A01"], "evidenceQuotes": [{"articleId": "A01", "fact": "안전점검 보도"}], "certainty": "confirmed", "electricalCauseStatus": "not_applicable", "kescoJurisdiction": "DIRECT", "jurisdictionReason": "공사 점검 업무", "excludedElements": [], "recommendation": "사실관계를 점검한다.", "actionLevel": "internal_review"}],
        "decisionPoints": [{"text": "확산 추이를 확인한다.", "articleIds": ["A01"]}],
        "actionItems": [{"priority": "review", "action": "사실관계를 점검한다.", "articleIds": ["A01"], "kescoJurisdiction": "DIRECT", "actionLevel": "internal_review", "evidence": "안전점검 보도", "uncertainty": "confirmed", "ownerType": "KESCO"}],
        "riskOutlook": {"text": "후속 보도가 이어질 수 있다.", "articleIds": ["A01"], "isInference": True},
        "limitations": [],
        "confidence": "medium",
    }

    class FakeOllama:
        calls = 0

        def generate(self, *, model, prompt, format_schema=None, cancel_token=None):  # noqa: ARG002
            self.calls += 1
            if self.calls == 1:
                return json.dumps(
                    {
                        "items": [{
                            "section": "core",
                            "articleFact": "안전점검 보도가 확인됐다.",
                            "attributedClaim": "",
                            "kescoInterpretation": "공사 관점에서 살펴볼 사안이다.",
                            "managementRecommendation": "사실관계를 점검할 필요가 있다.",
                            "articleIds": ["A01"],
                            "certainty": "confirmed",
                            "evidenceQuotes": [{"articleId": "A01", "fact": "안전점검 보도"}],
                            "electricalCauseStatus": "not_applicable",
                            "kescoJurisdiction": "DIRECT",
                            "jurisdictionReason": "공사 점검 업무",
                            "excludedElements": [],
                            "actionLevel": "internal_review",
                            "ownerType": "KESCO",
                        }],
                        "limitations": [],
                        "confidence": "medium",
                    },
                    ensure_ascii=False,
                )
            return json.dumps(analysis, ensure_ascii=False)

    app.state.ollama_client = FakeOllama()
    briefing = client.get(f"/api/briefings/{report_date}").json()["data"]
    analyzed = client.post(
        f"/api/briefings/{report_date}/analyze",
        json={"expectedRevision": briefing["revision"], "model": "gemma-test"},
    )
    assert analyzed.status_code == 200
    revision = analyzed.json()["data"]["briefingRevision"]
    client.post(
        f"/api/briefings/{report_date}/finalize", json={"expectedRevision": revision}
    )
    snapshot = client.get(
        f"/api/briefings/{report_date}/versions/1"
    ).json()["data"]["snapshot"]
    assert snapshot["evidence"]["A01"]["articleId"] == article_id
    assert snapshot["evidence"]["A01"]["article"]["title"]
    report = client.get(f"/report/{report_date}").text
    assert f'id="article-{article_id}"' in report
    assert "① 오늘 한줄" in report
    assert "② 언론 동향 분석" in report
    assert "③ 경영 참고사항" in report
    assert "직접 보도가 확인됐다." in report
    assert "후속 확인" not in report
    assert "후속 보도가 이어질 수 있다." not in report
    assert "의사결정 포인트" not in report
    assert "확산 추이를 확인한다." not in report
    assert "실행 항목" not in report
    assert "사실관계를 점검한다." in report
    assert "관련기사" in report
    assert "분석 근거" not in report
    assert "근거 기사 링크" not in report
    assert "관련 기사 모음" not in report
    assert 'class="evidence-list"' not in report
    assert "CEO 참고·지시사항" not in report
    assert "CEO 보고 편집본" not in report
    assert ">A01</" not in report


def test_schema_v4_backup_round_trip_preserves_final_version():
    source_date = "2026-09-04"
    _create_selected_article(source_date)
    briefing = client.get(f"/api/briefings/{source_date}").json()["data"]
    client.post(
        f"/api/briefings/{source_date}/finalize",
        json={"expectedRevision": briefing["revision"]},
    )
    payload = client.get(f"/api/exports/{source_date}.json").json()["data"]
    assert payload["schemaVersion"] == 12
    assert len(payload["briefingVersions"]) == 1

    target_date = "2026-09-05"
    imported = client.post(f"/api/exports/{target_date}.json", json=payload)
    assert imported.status_code == 200
    assert imported.json()["data"]["versionsImported"] == 1
    restored = client.get(f"/api/briefings/{target_date}/versions/1")
    assert restored.status_code == 200
    restored_snapshot = restored.json()["data"]["snapshot"]
    assert restored_snapshot["reportDate"] == target_date
    assert client.get(f"/report/{target_date}").status_code == 200


def test_final_export_scopes_and_immutable_import_conflict():
    report_date = "2026-09-06"
    _create_selected_article(report_date)
    briefing = client.get(f"/api/briefings/{report_date}").json()["data"]
    client.post(
        f"/api/briefings/{report_date}/finalize",
        json={"expectedRevision": briefing["revision"]},
    )

    latest = client.get(
        f"/api/exports/{report_date}.json", params={"scope": "latest-final"}
    )
    specified_csv = client.get(
        f"/api/exports/{report_date}.csv", params={"scope": "version:1"}
    )
    assert latest.status_code == 200
    assert latest.json()["data"]["briefingVersions"][0]["version"] == 1
    assert specified_csv.status_code == 200
    assert "안전점검 보도" in specified_csv.text
    assert client.get(
        f"/api/exports/{report_date}.json", params={"scope": "version:99"}
    ).status_code == 404

    payload = client.get(f"/api/exports/{report_date}.json").json()["data"]
    payload["briefingVersions"][0]["snapshot"]["briefing"]["actionNote"] = "변조"
    conflict = client.post(
        f"/api/exports/{report_date}.json?mode=replace", json=payload
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["details"]["reason"] == "immutable_final_snapshot_differs"
    preserved = client.get(f"/api/briefings/{report_date}/versions/1").json()["data"]
    assert preserved["snapshot"]["briefing"]["actionNote"] == "1차 지시"
