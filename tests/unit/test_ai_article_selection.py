import json

import pytest

from backend.app.services.ai.article_selection import (
    SelectionError,
    build_candidate_input,
    recommend,
    required_topic_groups,
)


def test_kesco_press_articles_are_excluded_from_ai_selection_candidates():
    articles = [
        {
            "id": "republication",
            "title": "공사 보도자료 전재",
            "origin": {"effectiveType": "kesco_republication"},
        },
        {
            "id": "based",
            "title": "공사 보도자료 기반",
            "origin": {"effectiveType": "kesco_based"},
        },
        {
            "id": "independent",
            "title": "언론사 독자 취재",
            "origin": {"effectiveType": "independent"},
        },
        {
            "id": "unclassified",
            "title": "출처 미분류 기사",
            "origin": None,
        },
    ]

    candidates, evidence = build_candidate_input(articles, [])

    assert set(evidence.values()) == {"independent", "unclassified"}
    assert {candidate["title"] for candidate in candidates} == {
        "언론사 독자 취재",
        "출처 미분류 기사",
    }


def test_low_importance_local_prevention_news_is_excluded():
    articles = [
        {
            "id": "mokpo-fire-station",
            "title": "목포소방서, 여름철 화재예방 행동요령 홍보",
            "description": "시민에게 전기 화재 예방수칙을 안내했다.",
            "eventType": "prevention",
            "relevanceScore": 88,
            "severityScore": 10,
        },
        {
            "id": "siheung-fire-station",
            "title": "시흥소방서, 민ㆍ관 합동 여름철 화재 예방 캠페인",
            "eventType": "prevention",
            "relevanceScore": 88,
            "severityScore": 10,
        },
        {
            "id": "national-campaign",
            "title": "전국 여름철 전기화재 예방 캠페인 확대",
            "eventType": "prevention",
        },
    ]

    _, evidence = build_candidate_input(articles, [])

    assert set(evidence.values()) == {"national-campaign"}


def test_high_impact_local_incident_remains_eligible():
    articles = [
        {
            "id": "local-incident",
            "title": "목포소방서, 공장 화재로 2명 중상·주민 대피",
            "description": "전기적 요인으로 추정되는 화재가 발생했다.",
            "eventType": "accident",
        }
    ]

    _, evidence = build_candidate_input(articles, [])

    assert set(evidence.values()) == {"local-incident"}


def test_overseas_incident_is_deprioritized_but_remains_eligible():
    articles = [
        {
            "id": "overseas-incident",
            "title": "미국 변전소 화재로 대규모 정전",
            "eventType": "accident",
            "relevanceScore": 90,
            "severityScore": 90,
        },
        {
            "id": "domestic-incident",
            "title": "국내 변전소 화재로 정전",
            "eventType": "accident",
            "relevanceScore": 70,
            "severityScore": 70,
        },
    ]

    candidates, evidence = build_candidate_input(articles, [])

    assert evidence == {"C01": "domestic-incident", "C02": "overseas-incident"}
    assert candidates[0]["overseasIncident"] is False
    assert candidates[1]["overseasIncident"] is True


def test_government_economy_and_ai_candidates_are_reserved_and_required():
    articles = [
        {
            "id": f"high-{index:02d}",
            "title": f"고득점 일반 기사 {index}",
            "relevanceScore": 100,
            "severityScore": 100,
        }
        for index in range(60)
    ]
    articles.extend(
        [
            {
                "id": "government",
                "title": "산업통상자원부 전력 정책 발표",
                "category": "government_meeting",
            },
            {
                "id": "economy",
                "title": "전기요금과 물가 전망",
                "category": "macro_economy",
            },
            {
                "id": "ai",
                "title": "AI 데이터센터 전력수요 증가",
                "category": "ai_trend",
            },
        ]
    )

    candidates, evidence = build_candidate_input(articles, [])
    required = required_topic_groups(articles, candidates, 20)

    assert len(candidates) == 60
    assert {"government", "economy", "ai"} <= set(evidence.values())
    assert required == ["government", "economy", "ai"]


def test_existing_selected_topic_satisfies_its_quota():
    articles = [
        {
            "id": "selected-government",
            "title": "정부 전력 정책 발표",
            "category": "government_meeting",
            "included": True,
        },
        {
            "id": "economy",
            "title": "전기요금 전망",
            "category": "macro_economy",
        },
        {
            "id": "ai",
            "title": "AI 전력수요 전망",
            "category": "ai_trend",
        },
    ]

    candidates, _ = build_candidate_input(articles, [])

    assert required_topic_groups(articles, candidates, 19) == ["economy", "ai"]


def test_ai_response_missing_required_topic_is_rejected_after_retry():
    class FakeClient:
        def __init__(self):
            self.calls = 0

        def generate(self, **_kwargs):
            self.calls += 1
            return json.dumps(
                {
                    "recommendations": [
                        {"evidenceId": "C03", "rank": 1, "reason": "AI 기사"},
                        {"evidenceId": "C04", "rank": 2, "reason": "일반 기사"},
                    ],
                    "limitations": [],
                }
            )

    client = FakeClient()
    candidates = [
        {"id": "C01", "topicGroups": ["government"]},
        {"id": "C02", "topicGroups": ["economy"]},
        {"id": "C03", "topicGroups": ["ai"]},
        {"id": "C04", "topicGroups": []},
    ]

    with pytest.raises(SelectionError, match="정부부처, 경제"):
        recommend(
            client,
            model="gemma-test",
            report_date="2026-07-17",
            target_count=2,
            candidates=candidates,
            evidence={candidate["id"]: candidate["id"] for candidate in candidates},
            required_groups=["government", "economy"],
        )

    assert client.calls == 2
