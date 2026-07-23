from backend.app.services.collection.dropped_issue import (
    discover_issues,
    is_entertainment_or_sports,
)
from backend.app.services.normalization.title import normalized_article_title


def _row(title: str, source: str, published_at: str = "2026-07-23T09:00:00Z", description: str = "") -> dict:
    return {
        "title": title,
        "normalized_title": normalized_article_title(title),
        "url": f"https://news.example/{abs(hash(title)) % 100000}",
        "source": source,
        "published_at": published_at,
        "description": description,
    }


def test_big_event_covered_by_many_outlets_becomes_an_issue():
    rows = [
        _row("부산 아파트 화재로 일가족 3명 사망", "한겨레"),
        _row("부산 아파트서 큰불…3명 숨져", "중앙일보"),
        _row("부산 아파트 화재 사망자 3명으로 늘어", "동아일보"),
        _row("부산 아파트 화재, 일가족 참변", "경향신문"),
        _row("부산 아파트 불…3명 사망", "국민일보"),
        _row("부산 아파트 화재 원인 조사 착수", "서울신문"),
        # 관련 없는 단발성 기사(잡음)
        _row("올여름 장마 이례적 늦은 시작", "연합뉴스"),
        _row("환율 소폭 상승 마감", "매일경제"),
    ]

    issues = discover_issues(rows, min_articles=5)

    assert len(issues) == 1
    assert "부산" in issues[0]["title"]
    assert issues[0]["articleCount"] == 6
    assert issues[0]["sourceCount"] == 6


def test_cluster_below_threshold_is_dropped():
    rows = [
        _row("대전 물류창고 화재 진화 중", "한겨레"),
        _row("대전 물류창고서 불…진화 작업", "중앙일보"),
        _row("대전 물류창고 화재 대응 2단계", "동아일보"),
        _row("대전 물류창고 화재 재산피해", "경향신문"),
    ]

    assert discover_issues(rows, min_articles=5) == []


def test_entertainment_and_sports_clusters_are_excluded():
    rows = [
        _row("인기 아이돌 그룹 컴백 무대 화제", "스포츠서울"),
        _row("아이돌 그룹 신곡 컴백 성공적", "스포츠조선"),
        _row("아이돌 컴백 무대 뜨거운 반응", "일간스포츠"),
        _row("아이돌 그룹 컴백 앨범 판매 신기록", "OSEN"),
        _row("아이돌 컴백 팬미팅 매진", "마이데일리"),
        _row("프로야구 오늘 경기 결과 정리", "스포츠동아"),
        _row("프로야구 홈런 더비 승부", "엑스포츠뉴스"),
        _row("프로야구 리그 순위 변동", "스포탈코리아"),
        _row("프로야구 선발승 소식", "점프볼"),
        _row("프로야구 국가대표 명단 발표", "베이스볼"),
    ]

    assert discover_issues(rows, min_articles=5) == []


def test_same_source_same_title_is_counted_once():
    rows = [
        _row("서울 지하철 사고로 운행 지연", "연합뉴스"),
        _row("서울 지하철 사고로 운행 지연", "연합뉴스"),
        _row("서울 지하철 사고로 운행 지연", "연합뉴스"),
        _row("서울 지하철 사고 승객 불편", "뉴시스"),
        _row("서울 지하철 사고 원인 조사", "뉴스1"),
    ]

    # 연합뉴스 동일 제목 3건은 1건으로 압축 → 서로 다른 3매체 3건뿐이라 5건 미달.
    assert discover_issues(rows, min_articles=5) == []


def test_top_issues_capped_and_sorted_by_size():
    events = {
        "인천 물류창고 폭발": [
            "인천 물류창고 폭발로 근로자 2명 부상",
            "인천 물류창고서 폭발 사고 발생",
            "인천 물류창고 폭발 원인 조사 착수",
            "인천 물류창고 폭발 현장 아수라장",
            "인천 물류창고 폭발 소방 대응 나서",
            "인천 물류창고 폭발 2명 병원 이송",
            "인천 물류창고 폭발 사고 수습 중",
        ],
        "광주 도심 정전": [
            "광주 도심 대규모 정전 발생",
            "광주 도심 정전으로 신호등 마비",
            "광주 도심 한때 정전에 시민 불편",
            "광주 도심 정전 복구 완료",
            "광주 도심 정전 원인 변전소 고장",
            "광주 도심 정전 피해 신고 속출",
        ],
        "울산 화학공장 누출": [
            "울산 화학공장 유독가스 누출",
            "울산 화학공장 가스 누출로 주민 대피",
            "울산 화학공장 누출 사고 조사",
            "울산 화학공장 누출 인근 통제",
            "울산 화학공장 누출 원인 규명",
        ],
    }
    rows = []
    for titles in events.values():
        for index, title in enumerate(titles):
            rows.append(_row(title, f"매체{index}-{title[:2]}"))

    issues = discover_issues(rows, min_articles=5, max_issues=2)

    assert len(issues) == 2
    assert issues[0]["articleCount"] == 7
    assert issues[1]["articleCount"] == 6


def test_bridge_article_does_not_chain_different_events_into_one_issue():
    rows = [
        _row("서울 지하철 정전으로 운행 중단", "서울신문"),
        _row("서울 지하철 정전 원인 조사", "경향신문"),
        _row("서울 지하철 정전 복구 작업", "국민일보"),
        # '정전·복구·작업'으로 위 기사 하나와 닿지만, 뒤의 제주 태풍 기사에 속한다.
        _row("제주 태풍 피해 정전 복구 작업", "한겨레"),
        _row("제주 태풍 피해로 도로 통제", "중앙일보"),
        _row("제주 태풍 피해 주민 긴급 대피", "동아일보"),
        _row("제주 태풍 피해 복구 지원 착수", "연합뉴스"),
    ]

    issues = discover_issues(rows, min_articles=3)

    assert sorted(issue["articleCount"] for issue in issues) == [3, 4]
    for issue in issues:
        titles = [article["title"] for article in issue["articles"]]
        assert not (
            any("서울 지하철" in title for title in titles)
            and any("제주 태풍" in title for title in titles)
        )


def test_is_entertainment_or_sports_flags():
    assert is_entertainment_or_sports("유명 배우 열애설 인정") is True
    assert is_entertainment_or_sports("프로축구 월드컵 예선 승리") is True
    assert is_entertainment_or_sports("전국 물류센터 전기설비 점검 강화") is False
