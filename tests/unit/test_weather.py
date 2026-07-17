from urllib.parse import parse_qs, urlsplit

from backend.app.services.weather.kma_client import (
    _request_json,
    build_daily_summaries,
    collect_alerts,
)
from backend.app.services.weather.region_config import load_regions
from backend.app.services.weather import collector as weather_collector
from backend.app.services.weather.risk_engine import build_signals, overall_level
from backend.app.services.weather.fallback import reuse_failed_providers


def test_official_warning_creates_grounded_electrical_risk_signal():
    signals = build_signals(
        [
            {
                "title": "호우경보 발효",
                "issuedAt": "2026-07-17T06:00:00+09:00",
                "regionIds": ["capital", "chungcheong"],
            }
        ]
    )

    assert len(signals) == 1
    assert signals[0]["hazard"] == "heavy_rain"
    assert signals[0]["level"] == "critical"
    assert "누전·감전 위험" in signals[0]["electricalRisks"]
    assert signals[0]["evidence"][0]["officialIssuedAt"]
    assert overall_level(signals, "success") == "critical"


def test_stale_or_failed_alert_source_never_becomes_normal():
    assert overall_level([], "failed") == "unknown"
    assert overall_level([], "partial") == "unknown"
    assert overall_level([], "success") == "normal"


def test_short_and_mid_forecasts_join_into_seven_days():
    short = [
        {"regionId": "capital", "fcstDate": "20260717", "category": "TMP", "fcstValue": "25"},
        {"regionId": "capital", "fcstDate": "20260717", "category": "TMX", "fcstValue": "31"},
        {"regionId": "capital", "fcstDate": "20260717", "category": "POP", "fcstValue": "70"},
        {"regionId": "capital", "fcstDate": "20260717", "category": "PCP", "fcstValue": "30.0~50.0mm"},
        {"regionId": "capital", "fcstDate": "20260717", "category": "PTY", "fcstValue": "1"},
    ]
    mid = [
        {"regionId": "capital", "kind": "land", "wf4Am": "흐리고 비", "rnSt4Am": 60, "wf4Pm": "흐림", "rnSt4Pm": 30},
        {"regionId": "capital", "kind": "temperature", "taMin4": 22, "taMax4": 30},
    ]

    days = build_daily_summaries(
        "2026-07-17", short, mid, [{"id": "capital", "label": "수도권"}]
    )

    assert len(days) == 7
    assert days[0]["weatherText"] == "비"
    assert days[0]["temperature"] == {"min": 25, "max": 31, "isNationalRange": True}
    assert days[0]["maxHourlyPrecipitation"] == {
        "text": "30.0~50.0mm",
        "min": 30.0,
        "max": 50.0,
        "unit": "mm/h",
    }
    assert days[4]["date"] == "2026-07-21"
    assert "비" in days[4]["weatherText"]
    assert days[4]["maxPrecipitationProbability"] == 60
    assert days[0]["regions"][0]["regionLabel"] == "수도권"
    assert days[0]["regions"][0]["temperature"]["min"] == 25


def test_encoded_public_data_key_is_not_double_encoded():
    requested_urls = []

    def getter(url, headers, timeout):  # noqa: ARG001
        requested_urls.append(url)
        return 200, '{"response":{"header":{"resultCode":"00"},"body":{}}}'

    _request_json(
        "https://apis.data.go.kr/example",
        {},
        service_key="abc%2Bdef%2Fghi%3D",
        getter=getter,
    )

    query = parse_qs(urlsplit(requested_urls[0]).query)
    assert query["serviceKey"] == ["abc+def/ghi="]


def test_current_and_preliminary_alerts_are_separated_and_all_hazards_are_kept():
    payload = {
        "response": {
            "header": {"resultCode": "00"},
            "body": {
                "items": {
                    "item": {
                        "tmFc": "202607170730",
                        "tmEf": "202607170900",
                        "t6": "강풍주의보 : 울릉도·독도\n건조주의보 : 경상북도",
                        "t7": "호우 예비특보 : 전라남도",
                        "other": "없음",
                    }
                }
            },
        }
    }

    def getter(url, headers, timeout):  # noqa: ARG001
        import json

        return 200, json.dumps(payload, ensure_ascii=False)

    collected = collect_alerts("key", load_regions()["regions"], getter)
    signals = build_signals(collected["items"])

    assert len(collected["items"]) == 3
    assert collected["items"][2]["preliminary"] is True
    assert {item["hazard"] for item in signals} == {
        "strong_wind",
        "dry",
        "heavy_rain",
    }
    assert next(item for item in signals if item["hazard"] == "heavy_rain")["regionIds"] == ["honam"]
    assert next(item for item in signals if item["hazard"] == "strong_wind")["regionIds"] == ["yeongnam"]


def test_combined_warning_lines_keep_hazard_specific_regions_and_severity():
    payload = {
        "response": {
            "header": {"resultCode": "00"},
            "body": {
                "items": {
                    "item": {
                        "tmFc": "202607172030",
                        "t6": "o 호우경보 : 경상북도(구미, 김천북부)\no 호우주의보 : 충청남도(아산, 청양)\no 폭염주의보 : 전라남도(광양, 순천), 제주도",
                        "t7": "",
                    }
                }
            },
        }
    }

    def getter(url, headers, timeout):  # noqa: ARG001
        import json

        return 200, json.dumps(payload, ensure_ascii=False)

    collected = collect_alerts("key", load_regions()["regions"], getter)
    signals = build_signals(collected["items"])

    assert len(collected["items"]) == 3
    assert [(item["hazard"], item["level"]) for item in signals] == [
        ("heavy_rain", "critical"),
        ("heavy_rain", "watch"),
        ("heat", "watch"),
    ]
    assert signals[0]["regionIds"] == ["yeongnam"]
    assert signals[1]["regionIds"] == ["chungcheong"]
    assert signals[2]["regionIds"] == ["honam", "jeju"]


def test_weather_region_grid_matches_2026_official_reference():
    regions = load_regions()["regions"]
    points = {
        point["id"]: (point["nx"], point["ny"])
        for region in regions
        for point in region["shortForecastPoints"]
    }

    assert points["seoul"] == (60, 127)
    assert points["chuncheon"] == (73, 134)
    assert points["seogwipo"] == (53, 33)


def test_failed_alert_and_mid_sources_do_not_look_current_or_normal(monkeypatch):
    report_date = "2026-07-17"
    monkeypatch.setattr(
        weather_collector,
        "collect_alerts",
        lambda *args: {
            "provider": "alerts",
            "status": "failed",
            "items": [],
            "observations": [],
            "error": "403",
            "issuedAt": None,
        },
    )
    monkeypatch.setattr(
        weather_collector,
        "collect_short",
        lambda *args: {
            "provider": "shortForecast",
            "status": "success",
            "items": [
                {
                    "regionId": "capital",
                    "fcstDate": "20260717",
                    "category": "TMP",
                    "fcstValue": "25",
                }
            ],
            "observations": [],
            "error": None,
            "issuedAt": "2026-07-17T17:00:00+09:00",
        },
    )
    monkeypatch.setattr(
        weather_collector,
        "collect_mid",
        lambda *args: {
            "provider": "midForecast",
            "status": "failed",
            "items": [],
            "observations": [],
            "error": "403",
            "issuedAt": "2026-07-17T18:00:00+09:00",
        },
    )

    result = weather_collector.collect("key", report_date, getter=lambda *args: None)

    assert result["overallLevel"] == "unknown"
    assert result["days"][0]["riskLevel"] == "unknown"
    assert result["issuedAt"] == "2026-07-17T17:00:00+09:00"


def test_failed_providers_reuse_previous_context_as_stale():
    current = {
        "sourceStatus": {
            "alerts": {"status": "failed", "issuedAt": None, "error": "timeout"},
            "shortForecast": {"status": "success", "issuedAt": "2026-07-17T05:00:00+09:00", "error": None},
            "midForecast": {"status": "failed", "issuedAt": None, "error": "403"},
        },
        "days": [{"date": f"2026-07-{17 + index:02d}", "weatherText": "신규"} for index in range(7)],
        "alerts": [],
        "signals": [],
        "overallLevel": "unknown",
        "issuedAt": "2026-07-17T05:00:00+09:00",
        "regionConfigVersion": "regions-v1",
        "riskRuleVersion": "rules-v1",
        "inputSignature": "current",
    }
    previous = {
        "sourceStatus": {
            "alerts": {"status": "success", "issuedAt": "2026-07-17T04:00:00+09:00"},
            "midForecast": {"status": "success", "issuedAt": "2026-07-16T18:00:00+09:00"},
        },
        "days": [{"date": f"2026-07-{17 + index:02d}", "weatherText": "이전"} for index in range(7)],
        "alerts": [{"title": "서울 호우주의보", "issuedAt": "2026-07-17T04:00:00+09:00", "regionIds": ["capital"]}],
    }

    merged = reuse_failed_providers(current, previous)

    assert merged["sourceStatus"]["alerts"]["status"] == "stale"
    assert merged["sourceStatus"]["midForecast"]["status"] == "stale"
    assert merged["days"][0]["weatherText"] == "신규"
    assert merged["days"][4]["weatherText"] == "이전"
    assert merged["overallLevel"] == "watch"
    assert merged["inputSignature"] != "current"


def test_partial_provider_reuses_only_failed_region_and_rebuilds_national_summary():
    current = {
        "providers": [
            {"provider": "shortForecast", "status": "partial", "failedRegionIds": ["chungcheong"]}
        ],
        "sourceStatus": {
            "alerts": {"status": "success", "issuedAt": "2026-07-17T06:00:00+09:00"},
            "shortForecast": {"status": "partial", "issuedAt": "2026-07-17T05:00:00+09:00", "error": "청주 502"},
            "midForecast": {"status": "success", "issuedAt": "2026-07-16T18:00:00+09:00"},
        },
        "days": [
            {
                "date": f"2026-07-{17 + index:02d}",
                "regions": [
                    {"regionId": "capital", "weatherText": "맑음", "temperature": {"min": 25, "max": 31}, "maxPrecipitationProbability": 10, "maxWindSpeed": 2},
                    {"regionId": "chungcheong", "weatherText": "맑음", "temperature": {"min": 26, "max": 32}, "maxPrecipitationProbability": 10, "maxWindSpeed": 2},
                ],
            }
            for index in range(7)
        ],
        "alerts": [],
        "signals": [],
        "regionConfigVersion": "regions-v1",
        "riskRuleVersion": "rules-v1",
    }
    previous = {
        "sourceStatus": current["sourceStatus"],
        "alerts": [],
        "days": [
            {
                "date": f"2026-07-{17 + index:02d}",
                "regions": [
                    {"regionId": "capital", "weatherText": "맑음", "temperature": {"min": 20, "max": 30}, "maxPrecipitationProbability": 20, "maxWindSpeed": 3},
                    {"regionId": "chungcheong", "weatherText": "비", "temperature": {"min": 18, "max": 28}, "maxPrecipitationProbability": 90, "maxWindSpeed": 7},
                ],
            }
            for index in range(7)
        ],
    }

    merged = reuse_failed_providers(current, previous)

    assert merged["sourceStatus"]["shortForecast"]["status"] == "partial"
    assert merged["days"][0]["weatherText"] == "비"
    assert merged["days"][0]["temperature"]["min"] == 18
    assert merged["days"][0]["maxPrecipitationProbability"] == 90
