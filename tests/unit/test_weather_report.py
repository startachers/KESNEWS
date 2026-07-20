from backend.app.services.reports.renderer import _render_weather


def test_ceo_report_omits_weather_provider_diagnostics_but_keeps_forecast():
    snapshot = {
        "weather": {
            "attachment": {"includeInReport": True},
            "context": {
                "issuedAt": "2026-07-20T10:40:00+09:00",
                "sourceStatus": {
                    "alerts": {"status": "success"},
                    "shortForecast": {"status": "success"},
                    "midForecast": {"status": "partial", "error": "internal error"},
                },
                "days": [
                    {
                        "date": "2026-07-20",
                        "temperature": {"min": 23, "max": 35},
                        "maxHourlyPrecipitation": {"max": 50},
                        "dailyPrecipitation": {"max": 200},
                    }
                ],
                "riskSignals": [
                    {
                        "hazard": "heavy_rain",
                        "electricalRisks": ["침수·누전·감전 위험"],
                        "regionIds": ["capital"],
                    }
                ],
            },
        }
    }

    report = _render_weather(snapshot)

    assert "기상 특이사항" in report
    assert "(폭우)" in report
    assert "침수·누전·감전 위험" in report
    assert "일부 기상정보 상태" not in report
    assert "midForecast" not in report
    assert "partial" not in report
    assert "internal error" not in report
