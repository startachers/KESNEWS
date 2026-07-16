import json
import re
from pathlib import Path

from backend.app.services.collection.collector import replace_people_tokens

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
]


def test_automated_and_frontend_defaults_contain_same_17_query_groups():
    config_paths = [ROOT / "config/automated_collection.json.example"]
    local_config = ROOT / "config/automated_collection.json"
    if local_config.exists():
        config_paths.append(local_config)
    for path in config_paths:
        config = json.loads(path.read_text(encoding="utf-8"))
        assert [query["id"] for query in config["queries"]] == QUERY_IDS

    store_source = (ROOT / "frontend/js/state/store.js").read_text(encoding="utf-8")
    default_block = store_source.split("export const CATEGORY_COLORS", 1)[0]
    assert re.findall(r'\{ id: "([^"]+)"', default_block) == QUERY_IDS
    assert "settingsVersion: 3" in default_block


def test_query_settings_screen_defines_five_groups_and_every_query_id():
    source = (ROOT / "frontend/js/ui/dialogs.js").read_text(encoding="utf-8")
    for label in ("기관·평판", "정부 메시지", "공공기관 경영", "사고·안전", "제도·성과·전략"):
        assert label in source
    for query_id in QUERY_IDS:
        assert query_id in source


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
