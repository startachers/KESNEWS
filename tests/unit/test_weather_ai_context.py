from backend.app.services.weather.ai_context import (
    build_weather_ai_context,
    validated_weather_message,
)


def _weather():
    return {
        "attachment": {"reviewedAt": "2026-07-17T06:20:00+09:00", "editorNote": "확인"},
        "context": {
            "id": "context-1",
            "inputSignature": "source-signature",
            "sourceStatus": {"alerts": {"issuedAt": "2026-07-17T06:10:00+09:00"}},
            "regionConfigVersion": "regions-v1",
            "riskRuleVersion": "rules-v1",
            "riskSignals": [
                {
                    "id": "signal-1",
                    "hazard": "heavy_rain",
                    "level": "watch",
                    "regionIds": ["capital"],
                    "electricalRisks": ["침수"],
                    "recommendedChecks": ["취약시설 점검"],
                }
            ],
        },
    }


def test_weather_context_uses_separate_w_evidence_and_template():
    context, evidence, fallback = build_weather_ai_context(_weather())
    assert evidence == {"W01": "signal-1"}
    assert context["riskSignals"][0]["id"] == "W01"
    assert fallback["weatherSignalIds"] == ["W01"]
    assert "침수" in fallback["text"]


def test_invalid_weather_evidence_uses_template_without_rejecting_article_analysis():
    context, _, fallback = build_weather_ai_context(_weather())
    message, warning = validated_weather_message(
        {"text": "전국 경보", "weatherSignalIds": ["W99"]}, context, fallback
    )
    assert message == fallback
    assert warning["resolution"] == "template_fallback"
