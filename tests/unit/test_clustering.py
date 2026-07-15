from datetime import datetime, timezone

from backend.app.services.clustering.service import build_clusters, input_signature, issue_status


AS_OF = datetime(2026, 7, 15, 12, tzinfo=timezone.utc)


def _article(article_id: str, **overrides):
    article = {
        "id": article_id,
        "title": "전주 아파트 대규모 정전 발생 500세대 불편",
        "description": "전주 완산구 아파트 변압기 고장으로 정전이 발생했다",
        "source": "연합뉴스",
        "publishedAt": "2026-07-15T05:00:00Z",
        "relevanceScore": 40,
        "severityScore": 85,
        "directMention": False,
    }
    article.update(overrides)
    return article


def test_same_event_articles_cluster_but_original_articles_remain_members():
    clusters = build_clusters(
        [
            _article("a1"),
            _article(
                "a2",
                title="전주 완산구 아파트 정전…500가구 전력 끊겨",
                description="변압기 고장으로 주민들이 불편을 겪었다",
                source="KBS",
                publishedAt="2026-07-15T08:00:00Z",
            ),
        ],
        AS_OF,
    )
    assert len(clusters) == 1
    assert set(clusters[0]["articleIds"]) == {"a1", "a2"}
    assert clusters[0]["spreadScore"] == 60
    assert clusters[0]["autoReasons"]["spread"] == {
        "distinctSourceCount": 2,
        "majorOutletIncluded": True,
        "recent24hArticleCount": 2,
        "score": 60,
    }


def test_unrelated_articles_do_not_cluster():
    clusters = build_clusters(
        [
            _article("a1"),
            _article(
                "a2",
                title="한국전기안전공사 여름철 전기화재 예방 캠페인",
                description="전기화재 예방 홍보를 진행했다",
                source="지역일보",
                relevanceScore=100,
                severityScore=10,
                directMention=True,
            ),
        ],
        AS_OF,
    )
    assert {frozenset(cluster["articleIds"]) for cluster in clusters} == {
        frozenset({"a1"}),
        frozenset({"a2"}),
    }


def test_issue_status_transitions_follow_recent_article_windows():
    assert issue_status(["2026-07-15T05:00:00Z"], AS_OF) == "new"
    assert issue_status(
        ["2026-07-13T10:00:00Z", "2026-07-15T08:00:00Z", "2026-07-15T09:00:00Z"],
        AS_OF,
    ) == "expanding"
    assert issue_status(["2026-07-12T13:00:00Z"], AS_OF) == "cooling"
    assert issue_status(["2026-07-11T11:00:00Z"], AS_OF) == "closed"


def test_input_signature_covers_values_used_by_clustering():
    article = _article("a1")
    baseline = input_signature([article])

    for field, value in (
        ("relevanceScore", 41),
        ("severityScore", 84),
        ("directMention", True),
    ):
        changed = {**article, field: value}
        assert input_signature([changed]) != baseline
