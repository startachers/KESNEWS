from datetime import datetime, timezone

from backend.app.services.review_priority import rank_issues


def _issue(index: int, *, relevance: int, severity: int, event_type: str, direct: bool = False):
    return {
        "id": f"issue-{index:03d}",
        "autoStatus": "new",
        "lastSeenAt": "2026-07-16T08:00:00Z",
        "directMention": direct,
        "members": [{
            "id": f"article-{index:03d}",
            "source": "연합뉴스" if index == 1 else f"매체 {index}",
            "relevanceScore": relevance,
            "severityScore": severity,
            "eventType": event_type,
        }],
    }


def test_review_score_uses_urgency_and_response_suitability_components():
    ranked = rank_issues(
        [_issue(1, relevance=100, severity=80, event_type="management_risk", direct=True)],
        datetime(2026, 7, 16, 12, tzinfo=timezone.utc),
    )
    result = ranked[0]
    assert result["autoReviewScore"] >= 90
    assert result["autoReviewStars"] == 5
    components = result["reviewReasons"]["components"]
    assert components["urgency"]["weight"] == 0.15
    assert components["responseSuitability"]["weight"] == 0.10
    assert components["responseSuitability"]["recommendedMode"] == "proactive"


def test_rank_bands_are_caps_not_quotas():
    issues = [
        _issue(index, relevance=15, severity=5, event_type="general")
        for index in range(1, 22)
    ]
    ranked = rank_issues(issues, datetime(2026, 7, 16, 12, tzinfo=timezone.utc))
    assert len(ranked) == 21
    assert all(item["autoReviewStars"] <= 2 for item in ranked)
    assert not any(item["autoReviewStars"] >= 4 for item in ranked[:10])
    assert [item["autoReviewRank"] for item in ranked] == list(range(1, 22))
