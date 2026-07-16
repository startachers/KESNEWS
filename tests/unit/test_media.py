from backend.app.services.media import (
    domain_matches,
    identify_trusted_publisher,
    load_trusted_media_config,
    normalize_hostname,
)


def test_default_allowlist_contains_fifty_publishers():
    config = load_trusted_media_config()
    assert len(config["trusted_media"]) == 50
    assert config["trusted_media"][0]["id"] == "yonhap"
    assert {publisher["id"] for publisher in config["trusted_media"]} >= {
        "electimes",
        "energyplatform",
        "fpn119",
        "busan",
    }


def test_portals_and_republishers_remain_untrusted():
    for url in (
        "https://www.msn.com/ko-kr/news/other/article",
        "https://news.nate.com/view/20260716n12345",
        "https://v.daum.net/v/20260716120000000",
        "https://www.vietnam.vn/ko/example",
    ):
        decision = identify_trusted_publisher({"provider": "GDELT", "url": url})
        assert decision.allowed is False
        assert decision.reason == "untrusted_media"


def test_hostname_normalization_and_domain_boundary():
    assert normalize_hostname("https://WWW.News.KBS.CO.KR/path") == "news.kbs.co.kr"
    assert domain_matches("news.kbs.co.kr", "kbs.co.kr") is True
    assert domain_matches("fakekbs.co.kr", "kbs.co.kr") is False


def test_google_uses_source_url_and_rejects_missing_source():
    trusted = identify_trusted_publisher(
        {
            "provider": "Google 뉴스 RSS",
            "url": "https://news.google.com/rss/articles/1",
            "sourceUrl": "https://www.chosun.com/national/1",
        }
    )
    unknown = identify_trusted_publisher(
        {
            "provider": "Google 뉴스 RSS",
            "url": "https://www.chosun.com/national/1",
            "sourceUrl": "",
        }
    )
    assert (trusted.publisher_id, trusted.allowed) == ("chosun", True)
    assert unknown.reason == "unknown_publisher"
    assert unknown.allowed is False


def test_official_and_incident_official_sources_are_exempt():
    president = identify_trusted_publisher(
        {"provider": "GDELT", "url": "https://www.president.go.kr/newsroom"}
    )
    fire_service = identify_trusted_publisher(
        {"provider": "GDELT", "url": "https://www.nfa.go.kr/incident"}
    )
    assert president.reason == "official_source"
    assert fire_service.reason == "official_source"


def test_untrusted_incident_is_not_automatically_allowed():
    decision = identify_trusted_publisher(
        {"provider": "GDELT", "url": "https://local-news.example/fire"},
        incident_matched=True,
    )
    assert decision.allowed is False
    assert decision.reason == "untrusted_media"


def test_approved_incident_medium_is_allowed_only_for_incident():
    config = load_trusted_media_config()
    config["approved_incident_media"] = [
        {"id": "regional-approved", "name": "승인지역지", "domains": ["regional.example"]}
    ]
    article = {"provider": "GDELT", "url": "https://news.regional.example/fire"}
    assert identify_trusted_publisher(
        article, config=config, incident_matched=True
    ).publisher_id == "regional-approved"
    assert identify_trusted_publisher(
        article, config=config, incident_matched=False
    ).allowed is False
