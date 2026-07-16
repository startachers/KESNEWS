import json
import re
from pathlib import Path

from backend.app.services.collection.collector import query_max_records, replace_people_tokens

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
    "major_fire_breaking",
    "new_industry_safety",
    "law_standard_plan",
    "kesco_achievement",
    "strategic_trend",
    "renewable_ess_industry",
    "ev_industry",
    "macro_economy",
    "ai_trend",
]


def test_automated_and_frontend_defaults_contain_same_21_query_groups():
    config_paths = [ROOT / "config/automated_collection.json.example"]
    local_config = ROOT / "config/automated_collection.json"
    if local_config.exists():
        config_paths.append(local_config)
    for path in config_paths:
        config = json.loads(path.read_text(encoding="utf-8"))
        assert [query["id"] for query in config["queries"]] == QUERY_IDS
        by_id = {query["id"]: query for query in config["queries"]}
        assert by_id["macro_economy"]["maxRecords"] == 20
        assert by_id["ai_trend"]["maxRecords"] == 20

    store_source = (ROOT / "frontend/js/state/store.js").read_text(encoding="utf-8")
    default_block = store_source.split("export const CATEGORY_COLORS", 1)[0]
    assert re.findall(r'\{ id: "([^"]+)"', default_block) == QUERY_IDS
    assert "settingsVersion: 4" in default_block
    assert default_block.count("maxRecords: 20") == 2


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


def test_query_max_records_uses_positive_override_or_global_default():
    assert query_max_records({"maxRecords": 20}, 50) == 20
    assert query_max_records({}, 50) == 50
    assert query_max_records({"maxRecords": 0}, 50) == 50
    assert query_max_records({"maxRecords": "invalid"}, 50) == 50


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
