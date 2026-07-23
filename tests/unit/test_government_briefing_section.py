from backend.app.services.ai.article_selection import is_government_article
from backend.app.services.reports.renderer import (
    _government_evidence_ids,
    _render_government_reference,
    _render_management_reference,
)


def test_is_government_article_by_press_release_flag_or_category():
    assert is_government_article({"governmentPressRelease": True})
    assert is_government_article({"category": "prime_minister_message"})
    assert is_government_article({"category": "government_meeting"})
    assert not is_government_article({"category": "electrical_safety"})
    assert not is_government_article({})


def _evidence(mapping):
    return {
        evidence_id: {"articleId": evidence_id, "article": article}
        for evidence_id, article in mapping.items()
    }


def test_government_evidence_ids_detects_flag_and_category():
    evidence = _evidence(
        {
            "A01": {"governmentPressRelease": True, "title": "국무조정실 발표"},
            "A02": {"category": "climate_minister_message", "title": "기후에너지환경부"},
            "A03": {"category": "electrical_safety", "title": "일반 기사"},
        }
    )
    assert _government_evidence_ids(evidence) == {"A01", "A02"}


def test_government_reference_section_separates_from_management():
    evidence = _evidence(
        {
            "A01": {"governmentPressRelease": True, "title": "정책 브리핑", "source": "정책브리핑"},
            "A02": {"category": "electrical_safety", "title": "전기안전 참고"},
        }
    )
    analysis = {
        "keyIssues": [
            {
                "urgency": "reference",
                "kescoJurisdiction": "OUT_OF_SCOPE",
                "summary": "정부가 에너지 정책 방향을 발표했다.",
                "managementImpact": "요금 체계 변화 가능성.",
                "articleIds": ["A01"],
            },
            {
                "urgency": "reference",
                "kescoJurisdiction": "MONITORING",
                "summary": "전기안전 관련 참고 동향.",
                "managementImpact": "점검 수요 증가.",
                "articleIds": ["A02"],
            },
        ],
        "actionItems": [],
    }

    gov = _render_government_reference(analysis, evidence)
    mgmt = _render_management_reference(analysis, evidence)

    assert "에너지 정책 방향" in gov
    assert "전기안전 관련 참고" not in gov
    # 비정부 참고 동향은 경영 참고사항으로 병합된다.
    assert "전기안전 관련 참고" in mgmt
    assert "에너지 정책 방향" not in mgmt


def test_government_reference_fallback_lists_unmatched_checked_articles():
    evidence = _evidence(
        {
            "A01": {
                "governmentPressRelease": True,
                "title": "국무회의 주요 의결사항",
                "source": "국무조정실",
            },
        }
    )
    # keyIssue가 해당 기사를 다루지 않아도 제목·출처 한 줄로 보강된다.
    analysis = {"keyIssues": [], "actionItems": []}

    gov = _render_government_reference(analysis, evidence)

    assert "국무회의 주요 의결사항" in gov
    assert "국무조정실" in gov


def test_no_government_evidence_yields_empty_section():
    evidence = _evidence({"A01": {"category": "electrical_safety", "title": "일반"}})
    analysis = {
        "keyIssues": [
            {
                "urgency": "reference",
                "kescoJurisdiction": "MONITORING",
                "summary": "일반 참고 동향.",
                "managementImpact": "",
                "articleIds": ["A01"],
            }
        ],
        "actionItems": [],
    }

    assert _render_government_reference(analysis, evidence) == ""
    # 정부 항목이 없으면 기존과 동일하게 참고 동향은 ③에 남는다.
    assert "일반 참고 동향" in _render_management_reference(analysis, evidence)
