-- 기관 어댑터 source_id 우선 병합: (provider, provider_item_key) 조회용 색인.
CREATE INDEX IF NOT EXISTS idx_article_observations_provider_key
    ON article_observations(provider, provider_item_key)
    WHERE provider_item_key IS NOT NULL;
