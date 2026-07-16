import json
from pathlib import Path

from backend.app.services.collection import me_press, opm_press, policy_briefing

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "gov"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_opm_press_parses_article_no_and_department():
    items = opm_press._parse_rows(_read("opm_press_list.html"))
    assert len(items) == 2
    first = items[0]
    assert first["sourceId"] == "opm:162857"
    assert first["title"] == "[보도자료] 「2027년도 기후예산(안) 검토 결과」 심의·의결"
    assert first["description"] == "국가기후위기대응위원회 사무처"
    assert first["url"] == "https://www.opm.go.kr/opm/news/press-release.do?mode=view&articleNo=162857"
    assert first["pubDate"] == "2026-07-16T00:00:00Z"
    assert first["provider"] == "국무조정실 보도자료"


def test_opm_press_fetch_applies_max_records(monkeypatch):
    monkeypatch.setattr(opm_press, "http_get", lambda *a, **k: (200, _read("opm_press_list.html")))
    result = opm_press.fetch_opm_press(1)
    assert len(result["items"]) == 1
    assert result["provider"] == "국무조정실 보도자료"


def test_me_press_parses_board_id_and_department():
    items = me_press._parse_rows(_read("me_press_list.html"))
    assert len(items) == 2
    first = items[0]
    assert first["sourceId"] == "me:1877940"
    assert first["title"] == "기후부 장관, 전남광주특별시에서 호남권 반도체 산단 전력공급 계획안 점검"
    assert first["description"] == "전력망정책과"
    assert "boardId=1877940" in first["url"]
    assert "jsessionid" not in first["url"]
    assert first["pubDate"] == "2026-07-16T00:00:00Z"


def test_me_press_fetch_applies_max_records(monkeypatch):
    monkeypatch.setattr(me_press, "http_get", lambda *a, **k: (200, _read("me_press_list.html")))
    result = me_press.fetch_me_press(1)
    assert len(result["items"]) == 1


def test_policy_briefing_returns_empty_without_service_key():
    result = policy_briefing.fetch_policy_briefing("", "", 10)
    assert result == {"items": [], "provider": "정책브리핑 API"}


def test_policy_briefing_parses_standard_envelope(monkeypatch):
    payload = {
        "response": {
            "body": {
                "items": {
                    "item": [
                        {
                            "title": "전기안전 대책 발표",
                            "pDeptNm": "기후에너지환경부",
                            "insertDt": "2026-07-16 09:00:00",
                            "url": "https://www.korea.kr/briefing/pressReleaseView.do?newsId=1",
                            "newsId": "123456",
                        }
                    ]
                }
            }
        }
    }
    monkeypatch.setattr(policy_briefing, "http_get", lambda *a, **k: (200, json.dumps(payload)))
    result = policy_briefing.fetch_policy_briefing("test-key", "", 10)
    items = result["items"]
    assert len(items) == 1
    assert items[0]["title"] == "전기안전 대책 발표"
    assert items[0]["sourceId"] == "policy-briefing:123456"
    assert items[0]["description"] == "기후에너지환경부"


def test_policy_briefing_accepts_single_item_dict(monkeypatch):
    payload = {"response": {"body": {"items": {"item": {"title": "단일 아이템", "newsId": "9"}}}}}
    monkeypatch.setattr(policy_briefing, "http_get", lambda *a, **k: (200, json.dumps(payload)))
    result = policy_briefing.fetch_policy_briefing("test-key", "", 10)
    assert len(result["items"]) == 1
    assert result["items"][0]["title"] == "단일 아이템"
