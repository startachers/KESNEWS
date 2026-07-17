from datetime import datetime, timezone

from backend.app.services.clustering import service as clustering_service
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


def test_articles_from_same_kesco_press_release_share_one_origin_cluster():
    clusters = build_clusters(
        [
            _article(
                "a1",
                title="취약계층 전기안전 협력 확대",
                description="복지위기가구 무료 점검을 실시한다",
                pressReleaseId="kesco:171545",
                pressReleaseTitle="복지 사각지대도 전기안전 지킨다",
                originType="kesco_republication",
            ),
            _article(
                "a2",
                title="사회복지협의회와 촘촘한 안전망 구축",
                description="노후 전기설비 개보수를 지원한다",
                source="지역일보",
                pressReleaseId="kesco:171545",
                pressReleaseTitle="복지 사각지대도 전기안전 지킨다",
                originType="kesco_based",
            ),
        ],
        AS_OF,
    )

    assert len(clusters) == 1
    assert set(clusters[0]["articleIds"]) == {"a1", "a2"}
    assert clusters[0]["autoReasons"]["origin"] == {
        "type": "kesco_press_release",
        "pressReleaseId": "kesco:171545",
        "pressReleaseTitle": "복지 사각지대도 전기안전 지킨다",
        "matchedArticleCount": 2,
    }


def test_same_event_clusters_when_headlines_use_different_wording_and_number_units():
    clusters = build_clusters(
        [
            _article(
                "a1",
                title="전주 아파트 대규모 정전 발생 500세대 불편",
                description="완산구 아파트에서 변압기 고장으로 전력 공급이 중단됐다",
            ),
            _article(
                "a2",
                title="한밤 전력 끊겨 주민 불편…전주 500가구 피해",
                description="완산구 공동주택 변압기 고장으로 전기가 끊겼다",
                source="KBS",
            ),
        ],
        AS_OF,
    )

    assert len(clusters) == 1
    assert set(clusters[0]["articleIds"]) == {"a1", "a2"}
    assert clusters[0]["autoReasons"]["algorithmVersion"] == "event-aware-title-tfidf-v3"


def test_broad_threshold_does_not_merge_unrelated_fires_without_shared_event_details():
    clusters = build_clusters(
        [
            _article(
                "bifc",
                title="부산 BIFC 건물서 충전 중이던 청소용 전동카트 배터리 화재",
                description="부산 남구 문현동 BIFC 지하 주차장에서 전동카트 배터리 화재가 발생했다",
            ),
            _article(
                "asan",
                title="아산 배방 옷수선 가게 화재…1천100만원 재산피해",
                description="충남 아산시 배방읍 옷수선 가게에서 불이 나 재산 피해가 발생했다",
            ),
        ],
        AS_OF,
        pair_threshold=0.15,
    )

    assert {frozenset(cluster["articleIds"]) for cluster in clusters} == {
        frozenset({"bifc"}),
        frozenset({"asan"}),
    }


def test_same_event_type_in_different_places_does_not_cluster_without_shared_details():
    clusters = build_clusters(
        [
            _article(
                "a1",
                title="전주 완산구 아파트 정전으로 주민 불편",
                description="전주 공동주택 변압기 고장이 원인으로 조사됐다",
            ),
            _article(
                "a2",
                title="부산 사하구 공장 정전으로 생산 차질",
                description="부산 산업단지 배전 설비 이상이 발생했다",
                source="KBS",
            ),
        ],
        AS_OF,
    )

    assert {frozenset(cluster["articleIds"]) for cluster in clusters} == {
        frozenset({"a1"}),
        frozenset({"a2"}),
    }


def test_weak_transitive_link_does_not_merge_two_different_events(monkeypatch):
    pair_scores = {
        frozenset({"a1", "bridge"}): 0.72,
        frozenset({"bridge", "a2"}): 0.70,
        frozenset({"a1", "a2"}): 0.10,
    }

    def controlled_pair_score(left, right, _left_vector, _right_vector):
        return pair_scores[frozenset({left["id"], right["id"]})]

    monkeypatch.setattr(clustering_service, "pair_score", controlled_pair_score)
    clusters = build_clusters(
        [_article("a1"), _article("bridge"), _article("a2")],
        AS_OF,
    )

    assert sorted(len(cluster["articleIds"]) for cluster in clusters) == [1, 2]


def test_similarity_threshold_changes_grouping_and_is_recorded(monkeypatch):
    def controlled_pair_score(_left, _right, _left_vector, _right_vector):
        return 0.48

    monkeypatch.setattr(clustering_service, "pair_score", controlled_pair_score)
    articles = [_article("a1"), _article("a2")]

    broad = build_clusters(articles, AS_OF, pair_threshold=0.40)
    strict = build_clusters(articles, AS_OF, pair_threshold=0.55)

    assert len(broad) == 1
    assert len(strict) == 2
    assert broad[0]["autoReasons"]["clustering"] == {
        "pairThreshold": 0.40,
        "minimumCrossScore": 0.25,
    }
    assert strict[0]["autoReasons"]["clustering"] == {
        "pairThreshold": 0.55,
        "minimumCrossScore": 0.40,
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
        ("originType", "kesco_based"),
        ("pressReleaseId", "kesco:171545"),
    ):
        changed = {**article, field: value}
        assert input_signature([changed]) != baseline
