from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from backend.app.api.envelope import error_response, ok_envelope
from backend.app.core.clock import now_iso
from backend.app.repositories import article_repository as articles_repo
from backend.app.repositories import briefing_repository as briefings_repo
from backend.app.repositories.database import get_connection
from backend.app.services.classification.service import classify_article
from backend.app.services.normalization.dates import since_bound_iso

router = APIRouter()

_CLASSIFIER_VERSION = "phase3-rules-v1"


class ManualArticleRequest(BaseModel):
    reportDate: str
    title: str
    source: str = ""
    url: str = ""
    pubDate: str | None = None
    description: str = ""
    category: str = "direct"
    forcedRisk: str | None = None
    riskKeywords: list[str] = Field(default_factory=list)
    positiveKeywords: list[str] = Field(default_factory=list)


@router.get("/api/articles")
async def list_articles(
    report_date: str = Query(...), include_dismissed: bool = Query(False)
) -> Any:
    connection = get_connection()
    try:
        items = articles_repo.list_candidates(connection, report_date, include_dismissed)
    finally:
        connection.close()
    return ok_envelope({"articles": items})


@router.post("/api/articles")
async def create_manual_article(request: ManualArticleRequest) -> Any:
    connection = get_connection()
    try:
        briefing = briefings_repo.get_by_date(connection, request.reportDate)
        if briefing is None:
            return error_response("BRIEFING_NOT_FOUND", f"{request.reportDate} 작업본이 없습니다.")

        pub_date = request.pubDate or now_iso()
        raw = {
            "title": request.title,
            "source": request.source,
            "url": request.url,
            "pubDate": pub_date,
            "description": request.description,
            "manual": True,
        }
        classified = classify_article(raw, request.riskKeywords, request.positiveKeywords)
        if request.forcedRisk and request.forcedRisk != "auto":
            classified["risk"] = request.forcedRisk
            if request.forcedRisk != "routine":
                classified["sentiment"] = "negative"

        with connection:
            since = since_bound_iso(pub_date, 96)
            match = articles_repo.find_matching_article(
                connection, url=request.url, title=request.title, published_at=pub_date, since_iso=since
            )
            if match is not None:
                article_id = match["id"]
                articles_repo.touch_article(connection, article_id, description=request.description)
                merged = True
            else:
                article_id = articles_repo.create_article(
                    connection,
                    url=request.url,
                    title=request.title,
                    source=request.source,
                    published_at=pub_date,
                    description=request.description,
                    category_hint=request.category,
                    manual=True,
                )
                merged = False

            articles_repo.insert_observation(
                connection,
                article_id=article_id,
                collection_run_provider_id=None,
                provider="manual",
                provider_item_key=None,
                query_group_id=None,
                raw_url=request.url,
                raw_title=request.title,
                raw_source=request.source,
                raw_published_at=pub_date,
                raw_description=request.description,
                raw_payload_json=None,
                dedup_method="new" if not merged else "fuzzy_same_copy",
                dedup_score=None,
            )
            articles_repo.upsert_assessment(
                connection,
                article_id=article_id,
                auto_category=request.category,
                auto_risk=classified["risk"],
                auto_risk_score=classified["riskScore"],
                auto_sentiment=classified["sentiment"],
                auto_reasons=classified["matchedKeywords"],
                classifier_version=_CLASSIFIER_VERSION,
            )
            briefings_repo.mark_selected(connection, briefing["id"], article_id)
    finally:
        connection.close()
    return ok_envelope({"id": article_id, "merged": merged})


@router.delete("/api/articles/{article_id}")
async def delete_article(article_id: str, confirm: bool = Query(False)) -> Any:
    connection = get_connection()
    try:
        row = articles_repo.get_article(connection, article_id)
        if row is None:
            return error_response("ARTICLE_NOT_FOUND", "기사를 찾을 수 없습니다.")
        if not row["manual"]:
            return error_response("ARTICLE_IN_USE", "수동으로 추가한 기사만 완전히 삭제할 수 있습니다.")
        if not confirm:
            return error_response("ARTICLE_IN_USE", "삭제하려면 confirm=true가 필요합니다.")
        if articles_repo.count_final_snapshot_references(connection, article_id) > 0:
            return error_response("ARTICLE_IN_USE", "최종 확정 보고에 포함된 기사는 삭제할 수 없습니다.")
        if articles_repo.count_briefing_references(connection, article_id) > 1:
            return error_response("ARTICLE_IN_USE", "다른 보고일에서도 참조 중인 기사는 삭제할 수 없습니다.")
        with connection:
            articles_repo.delete_article(connection, article_id)
    finally:
        connection.close()
    return ok_envelope({"id": article_id, "deleted": True})
