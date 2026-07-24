import json
from pathlib import Path

from backend.app.services.collection.collector import (
    _within_date_only_government_window,
    _within_lookback,
    fetch_naver_query,
    query_max_records,
    replace_people_tokens,
)

ROOT = Path(__file__).parents[2]
QUERY_IDS = [
    "kesco_direct",
    "kesco_reputation",
    "presidential_message",
    "prime_minister_message",
    "climate_minister_message",
    "government_meeting",
    "public_evaluation",
    "public_operations",
    "kesco_governance",
    "assembly_law",
    "electrical_accident",
    "power_outage",
    "weather",
    "major_fire_breaking",
    "new_industry_safety",
    "law_standard_plan",
    "kesco_achievement",
    "strategic_trend",
    "renewable_ess_industry",
    "ev_industry",
    "macro_economy",
    "ai_trend",
    "it_industry",
    "cyber_security",
    "labor_safety",
    "peer_agencies",
]


def test_server_defaults_are_the_single_source_for_26_query_groups():
    config = json.loads(
        (ROOT / "config/collection_settings.json").read_text(encoding="utf-8")
    )
    assert [query["id"] for query in config["queries"]] == QUERY_IDS
    by_id = {query["id"]: query for query in config["queries"]}
    assert all(1 <= len(query["naverQueries"]) <= 3 for query in config["queries"])
    assert sum(len(query["naverQueries"]) for query in config["queries"]) <= 78
    assert by_id["macro_economy"]["maxRecords"] == 20
    assert by_id["ai_trend"]["maxRecords"] == 20
    assert by_id["it_industry"]["maxRecords"] == 20
    assert {"삼성전자 SK하이닉스 반도체", "애플 엔비디아 AI", "글로벌 빅테크 IT"} == set(
        by_id["it_industry"]["naverQueries"]
    )
    assert by_id["peer_agencies"]["maxRecords"] == 20

    store_source = (ROOT / "frontend/js/state/store.js").read_text(encoding="utf-8")
    default_block = store_source.split("export const CATEGORY_COLORS", 1)[0]
    assert 'queries: []' in default_block
    assert "collection_settings.json" not in store_source
    assert "settingsVersion: 0" in default_block
    assert 'aiModel: "gemma4:31b"' in default_block
    assert "lookback: 24" in default_block


def test_query_settings_screen_defines_six_groups_and_every_query_id():
    source = (ROOT / "frontend/js/ui/dialogs.js").read_text(encoding="utf-8")
    for label in (
        "기관·평판",
        "정부 메시지",
        "공공기관 경영",
        "사고·안전",
        "제도·성과·전략",
        "산업·거시환경",
    ):
        assert label in source
    for query_id in QUERY_IDS:
        assert query_id in source

    html = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
    assert '<select id="settingMaxRecords"><option value="20">20건</option>' in html
    assert '<option value="400">400건 (권장)</option>' in html
    assert 'const otherOption = `<option value="other">기타</option>`;' in source


def test_query_max_records_uses_positive_override_or_global_default():
    assert query_max_records({"maxRecords": 20}, 50) == 20
    assert query_max_records({}, 50) == 50
    assert query_max_records({"maxRecords": 0}, 50) == 50
    assert query_max_records({"maxRecords": "invalid"}, 50) == 50


def test_collection_window_is_exactly_previous_24_hours_without_future_grace():
    report_date = "2025-01-15"

    assert _within_lookback("2025-01-14T14:59:59Z", report_date, 24) is True
    assert _within_lookback("2025-01-14T14:59:58Z", report_date, 24) is False
    assert _within_lookback("2025-01-15T15:00:00Z", report_date, 24) is False


def test_date_only_government_window_keeps_report_date_and_previous_seoul_date():
    report_date = "2026-07-23"

    assert _within_date_only_government_window("2026-07-23T00:00:00Z", report_date) is True
    assert _within_date_only_government_window("2026-07-22T00:00:00Z", report_date) is True
    assert _within_date_only_government_window("2026-07-21T00:00:00Z", report_date) is False


def test_naver_query_applies_the_same_per_query_limit(monkeypatch):
    monkeypatch.setattr(
        "backend.app.services.collection.collector.fetch_naver_news",
        lambda *args: [{"id": index} for index in range(50)],
    )

    result = fetch_naver_query("전기안전", "id", "secret", lambda value: True, 20)

    assert len(result["items"]) == 20


def test_people_tokens_expand_names_and_remove_empty_or_clauses(tmp_path):
    template = [
        {"id": "president", "query": '("대통령"{OR_current_president}) 전력망'},
        {"id": "prime", "query": '("국무총리"{OR_current_prime_minister}) 전력수급'},
        {"id": "minister", "query": '("기후에너지환경부"{OR_current_climate_minister}) 전기안전'},
    ]
    configured = tmp_path / "people.yaml"
    configured.write_text(
        'version: 1\npeople:\n  president: "홍길동"\n  prime_minister: "김총리"\n  climate_minister: ""\n',
        encoding="utf-8",
    )

    replaced = replace_people_tokens(template, configured)

    assert replaced[0]["query"] == '("대통령" OR "홍길동") 전력망'
    assert replaced[1]["query"] == '("국무총리" OR "김총리") 전력수급'
    assert replaced[2]["query"] == '("기후에너지환경부") 전기안전'
    assert all("{OR_current_" not in query["query"] for query in replaced)
    assert all('OR ""' not in query["query"] for query in replaced)
