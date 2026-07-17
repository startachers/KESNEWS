import json

import pytest

from backend.app.services.ai.article_selection import (
    SelectionError,
    build_candidate_input,
    recommend,
    preferred_topic_groups,
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


def test_overseas_incident_without_domestic_link_is_excluded():
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

    assert evidence == {"C01": "domestic-incident"}
    assert candidates[0]["overseasIncident"] is False


def test_overseas_incident_with_specific_domestic_policy_link_remains_eligible():
    articles = [{
        "id": "overseas-reference",
        "title": "미국 변전소 화재, 국내 전력설비 기준 개정에 시사점",
        "eventType": "accident",
    }]

    candidates, evidence = build_candidate_input(articles, [])

    assert evidence == {"C01": "overseas-reference"}
    assert candidates[0]["overseasIncident"] is True


def test_general_fire_without_electrical_connection_is_excluded():
    articles = [
        {"id": "bamboo", "title": "창녕 대나무밭 화재", "description": "쓰레기 소각 부주의"},
        {"id": "battery", "title": "BIFC 배터리 충전 중 화재", "eventType": "accident"},
    ]

    _, evidence = build_candidate_input(articles, [])

    assert set(evidence.values()) == {"battery"}


def test_real_case_candidate_order_prioritizes_kesco_and_statutory_work_over_severity():
    articles = [
        {
            "id": "apartment",
            "title": "기후차관, 노후 공동주택 전기안전 점검",
            "description": "한국전기안전공사가 여름철 전기재해 예방 점검을 실시했다.",
            "relevanceScore": 100,
            "severityScore": 10,
        },
        {
            "id": "aircon",
            "title": "에어컨 화재 4년 새 75% 증가",
            "description": "냉방기 전기화재 통계와 예방수칙을 분석했다.",
            "relevanceScore": 88,
            "severityScore": 10,
        },
        {
            "id": "bifc",
            "title": "BIFC 전동카트 배터리 충전 중 화재",
            "description": "리튬 배터리 설비 안전 문제가 제기됐다.",
            "relevanceScore": 90,
            "severityScore": 10,
        },
        {
            "id": "asan",
            "title": "아산 옷수선 가게 화재",
            "description": "전기적 요인인 절연열화로 추정되며 인명피해는 없다.",
            "relevanceScore": 90,
            "severityScore": 10,
        },
        {
            "id": "bamboo",
            "title": "창녕 대나무밭 화재로 60대 사망",
            "description": "쓰레기 소각 중 부주의로 불이 번진 것으로 추정된다.",
            "relevanceScore": 87,
            "severityScore": 100,
        },
    ]

    candidates, evidence = build_candidate_input(articles, [])

    ordered_ids = [evidence[item["id"]] for item in candidates]
    assert ordered_ids[0] == "apartment"
    assert ordered_ids.index("bifc") < ordered_ids.index("asan")
    assert ordered_ids.index("aircon") < ordered_ids.index("asan")
    assert "bamboo" not in ordered_ids


def test_candidate_compression_keeps_only_one_representative_per_issue():
    articles = [
        {
            "id": f"grid-{index}",
            "title": f"정부 전력망 정책 후속 보도 {index}",
            "relevanceScore": 90 - index,
        }
        for index in range(3)
    ]
    articles.append({"id": "aircon", "title": "에어컨 전기 화재 급증"})
    issues = [{
        "id": "grid-issue",
        "autoTitle": "전력망 정책",
        "articleIds": ["grid-0", "grid-1", "grid-2"],
    }]

    _, evidence = build_candidate_input(articles, issues)

    assert set(evidence.values()) == {"grid-0", "aircon"}


def test_tangential_body_keyword_does_not_make_unrelated_headline_a_candidate():
    articles = [
        {
            "id": "market-roundup",
            "title": "한미반도체 2분기 역대 최대 실적…반도체 업황 우려 완화",
            "description": (
                "한미반도체 실적과 여러 기업 동향을 전한다. "
                "삼성SDI의 UPS용 배터리가 화재 차단 테스트를 통과했다."
            ),
            "category": "new_industry_safety",
        },
        {
            "id": "kesco-cooperation",
            "title": "전북도, 안전한 분산에너지 활성화 협력방안 모색",
            "description": "한국전기안전공사 ESS 안전성 평가센터에서 회의를 열었다.",
        },
    ]

    _, evidence = build_candidate_input(articles, [])

    assert set(evidence.values()) == {"kesco-cooperation"}


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
                "title": "정부, 전기요금과 물가 정책 발표",
                "category": "macro_economy",
            },
            {
                "id": "ai",
                "title": "정부, AI 데이터센터 전력수요 정책 발표",
                "category": "ai_trend",
            },
        ]
    )

    candidates, evidence = build_candidate_input(articles, [])
    required = preferred_topic_groups(articles, candidates, 12)

    assert len(candidates) == 60
    assert {"government", "economy", "ai"} <= set(evidence.values())
    assert required == ["government", "economy", "ai"]


def test_existing_selected_topic_is_removed_from_supplemental_preferences():
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

    assert preferred_topic_groups(articles, candidates, 11) == ["economy", "ai"]


def test_ai_response_may_omit_preferred_topic_when_quality_is_insufficient():
    class FakeClient:
        def __init__(self):
            self.calls = 0

        def generate(self, **_kwargs):
            self.calls += 1
            return json.dumps(
                {
                    "recommendations": [
                        {"evidenceId": "C03", "rank": 1, "articleFact": "AI 기사", "kescoRelevance": "전력수요", "selectionReason": "경영 참고"},
                        {"evidenceId": "C04", "rank": 2, "articleFact": "일반 기사", "kescoRelevance": "간접", "selectionReason": "참고"},
                    ],
                    "limitations": [],
                }
            )

    client = FakeClient()
    candidates = [
        {"id": "C01", "kescoRelevanceLevel": 3, "topicGroups": ["government"]},
        {"id": "C02", "kescoRelevanceLevel": 3, "topicGroups": ["economy"]},
        {"id": "C03", "kescoRelevanceLevel": 4, "topicGroups": ["ai"]},
        {"id": "C04", "kescoRelevanceLevel": 2, "topicGroups": []},
    ]

    output = recommend(
        client,
        model="gemma-test",
        report_date="2026-07-17",
        target_count=2,
        candidates=candidates,
        evidence={candidate["id"]: candidate["id"] for candidate in candidates},
        preferred_groups=["government", "economy"],
    )

    assert len(output.result["recommendations"]) == 2
    assert client.calls == 1


def test_ai_response_with_fewer_than_target_count_is_rejected():
    class FakeClient:
        def generate(self, **_kwargs):
            return json.dumps({
                "recommendations": [
                    {
                        "evidenceId": "C01",
                        "rank": 1,
                        "articleFact": "공사 합동점검",
                        "kescoRelevance": "공사 직접 참여",
                        "selectionReason": "CEO 보고 가치가 확인됨",
                    }
                ],
                "limitations": ["나머지 후보는 품질 기준 미달"],
            })

    with pytest.raises(SelectionError, match="정확히 3건"):
        recommend(
            FakeClient(),
            model="gemma-test",
            report_date="2026-07-17",
            target_count=3,
            candidates=[
                {"id": "C01", "kescoRelevanceLevel": 5, "topicGroups": ["government"]},
                {"id": "C02", "kescoRelevanceLevel": 2, "topicGroups": []},
                {"id": "C03", "kescoRelevanceLevel": 2, "topicGroups": []},
            ],
            evidence={"C01": "a1", "C02": "a2", "C03": "a3"},
            preferred_groups=["government", "ai"],
        )


def test_ai_response_with_ten_items_is_completed_from_remaining_candidates():
    class FakeClient:
        def __init__(self):
            self.prompts = []

        def generate(self, **kwargs):
            self.prompts.append(kwargs["prompt"])
            if len(self.prompts) == 1:
                indexes = range(1, 11)
            else:
                indexes = range(11, 13)
            return json.dumps({
                "recommendations": [
                    {
                        "evidenceId": f"C{index:02d}",
                        "rank": index if len(self.prompts) == 1 else index - 10,
                        "articleFact": f"기사 사실 {index}",
                        "kescoRelevance": f"공사 연관성 {index}",
                        "selectionReason": f"선정 이유 {index}",
                    }
                    for index in indexes
                ],
                "limitations": [],
            })

    fake = FakeClient()
    candidates = [
        {
            "id": f"C{index:02d}",
            "title": f"전기안전 후보 {index}",
            "kescoRelevanceLevel": 2,
            "titleTopicAligned": True,
            "topicGroups": [],
            "issueIds": [],
        }
        for index in range(1, 61)
    ]

    output = recommend(
        fake,
        model="gemma-test",
        report_date="2026-07-17",
        target_count=12,
        candidates=candidates,
        evidence={candidate["id"]: candidate["id"] for candidate in candidates},
        preferred_groups=["government", "economy", "ai"],
    )

    assert len(output.result["recommendations"]) == 12
    assert [item["rank"] for item in output.result["recommendations"]] == list(range(1, 13))
    assert [item["evidenceId"] for item in output.result["recommendations"]][-2:] == [
        "C11",
        "C12",
    ]
    assert output.attempts == 2
    assert len(fake.prompts) == 2
    assert "정확히 2건" in fake.prompts[1]
    assert '"id": "C11"' in fake.prompts[1]
    assert '"id": "C01"' not in fake.prompts[1]


def test_general_economy_and_ai_articles_are_allowed_only_in_supplemental_ranks():
    class FakeClient:
        def generate(self, **_kwargs):
            return json.dumps({"recommendations": [
                {
                    "evidenceId": f"C{index:02d}",
                    "rank": index,
                    "articleFact": f"기사 사실 {index}",
                    "kescoRelevance": "공사 핵심" if index <= 6 else "CEO 일반 경영동향",
                    "selectionReason": "핵심" if index <= 6 else "경제·AI 참고",
                }
                for index in range(1, 9)
            ], "limitations": []})

    output = recommend(
        FakeClient(),
        model="gemma-test",
        report_date="2026-07-17",
        target_count=8,
        candidates=[
            *[
                {"id": f"C{index:02d}", "kescoRelevanceLevel": 2, "topicGroups": []}
                for index in range(1, 7)
            ],
            {"id": "C07", "kescoRelevanceLevel": 0, "topicGroups": ["economy"]},
            {"id": "C08", "kescoRelevanceLevel": 0, "topicGroups": ["ai"]},
        ],
        evidence={f"C{index:02d}": f"a{index}" for index in range(1, 9)},
        preferred_groups=["economy", "ai"],
    )

    assert len(output.result["recommendations"]) == 8


def test_ai_response_below_minimum_relevance_gate_is_rejected():
    class FakeClient:
        def generate(self, **_kwargs):
            return json.dumps({
                "recommendations": [{
                    "evidenceId": "C01",
                    "rank": 1,
                    "articleFact": "일반 기업 실적",
                    "kescoRelevance": "공사 연관 없음",
                    "selectionReason": "분야 수량 보충",
                }],
                "limitations": [],
            })

    with pytest.raises(SelectionError, match="품질 기준"):
        recommend(
            FakeClient(),
            model="gemma-test",
            report_date="2026-07-17",
            target_count=1,
            candidates=[{"id": "C01", "kescoRelevanceLevel": 0, "topicGroups": ["ai"]}],
            evidence={"C01": "a1"},
            preferred_groups=["ai"],
        )


def test_ai_response_with_two_articles_from_same_issue_is_rejected():
    class FakeClient:
        def generate(self, **_kwargs):
            return json.dumps({
                "recommendations": [
                    {
                        "evidenceId": "C01",
                        "rank": 1,
                        "articleFact": "대표 기사",
                        "kescoRelevance": "공사 직접 관련",
                        "selectionReason": "대표 보도",
                    },
                    {
                        "evidenceId": "C02",
                        "rank": 2,
                        "articleFact": "후속 기사",
                        "kescoRelevance": "공사 직접 관련",
                        "selectionReason": "추가 세부정보",
                    },
                ],
                "limitations": [],
            })

    with pytest.raises(SelectionError, match="동일 이슈"):
        recommend(
            FakeClient(),
            model="gemma-test",
            report_date="2026-07-17",
            target_count=2,
            candidates=[
                {
                    "id": "C01",
                    "kescoRelevanceLevel": 5,
                    "titleTopicAligned": True,
                    "issueIds": ["summer-inspection"],
                },
                {
                    "id": "C02",
                    "kescoRelevanceLevel": 5,
                    "titleTopicAligned": True,
                    "issueIds": ["summer-inspection"],
                },
            ],
            evidence={"C01": "a1", "C02": "a2"},
            preferred_groups=[],
        )


def test_ai_response_with_title_topic_mismatch_is_rejected():
    class FakeClient:
        def generate(self, **_kwargs):
            return json.dumps({
                "recommendations": [{
                    "evidenceId": "C01",
                    "rank": 1,
                    "articleFact": "본문 일부의 배터리 소식",
                    "kescoRelevance": "배터리 안전",
                    "selectionReason": "산업 참고",
                }],
                "limitations": [],
            })

    with pytest.raises(SelectionError, match="제목 핵심주제"):
        recommend(
            FakeClient(),
            model="gemma-test",
            report_date="2026-07-17",
            target_count=1,
            candidates=[{
                "id": "C01",
                "kescoRelevanceLevel": 4,
                "titleTopicAligned": False,
                "issueIds": [],
            }],
            evidence={"C01": "a1"},
            preferred_groups=[],
        )
