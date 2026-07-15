from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from backend.app.api.envelope import error_response, ok_envelope
from backend.app.core.clock import now_iso
from backend.app.repositories import article_repository as articles_repo
from backend.app.repositories import briefing_repository as briefings_repo
from backend.app.repositories import run_repository as runs_repo
from backend.app.repositories.database import get_connection
from backend.app.services.classification.service import CLASSIFIER_VERSION, classify_article
from backend.app.services.normalization.dates import since_bound_iso

router = APIRouter()


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


class AssessmentPatchRequest(BaseModel):
    finalCategory: str | None = None
    finalEventType: Literal[
        "accident", "prevention", "management_risk", "policy", "achievement", "community", "general", "mixed"
    ] | None = None
    finalPriority: Literal["required", "review", "reference"] | None = None
    finalTone: Literal["positive", "neutral", "negative"] | None = None


@router.get("/api/articles")
async def list_articles(
    report_date: str = Query(...), include_dismissed: bool = Query(False)
) -> Any:
    connection = get_connection()
    try:
        items = articles_repo.list_candidates(connection, report_date, include_dismissed)
        meta: dict[str, Any] = {"failedProviders": [], "lastGoodCollectionAt": None}
        latest_run = runs_repo.get_latest_run(connection, report_date)
        if latest_run is not None:
            meta["lastGoodCollectionAt"] = runs_repo.get_last_successful_finished_at(connection, report_date)
            if latest_run["status"] != "success":
                meta["failedProviders"] = runs_repo.failed_providers(connection, latest_run["id"])
                stale_ids = runs_repo.unrefreshed_candidate_ids(connection, report_date, latest_run["id"])
                for item in items:
                    if item["id"] in stale_ids:
                        item["stale"] = True
                        item["staleReason"] = "provider_failed"
        for item in items:
            item.setdefault("stale", False)
            item.setdefault("staleReason", None)
    finally:
        connection.close()
    return ok_envelope({"articles": items}, meta=meta)


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
                assessment={**classified["assessment"], "autoCategory": request.category},
                classifier_version=CLASSIFIER_VERSION,
            )
            if request.forcedRisk and request.forcedRisk != "auto":
                forced_priority = {
                    "critical": "required",
                    "watch": "review",
                    "routine": "reference",
                }.get(request.forcedRisk)
                if forced_priority:
                    articles_repo.patch_final_assessment(
                        connection,
                        article_id,
                        {
                            "finalPriority": forced_priority,
                            "finalTone": "negative" if forced_priority != "reference" else None,
                        },
                    )
            briefings_repo.mark_selected(connection, briefing["id"], article_id)
    finally:
        connection.close()
    return ok_envelope({"id": article_id, "merged": merged})


@router.patch("/api/articles/{article_id}/assessment")
async def patch_article_assessment(article_id: str, request: AssessmentPatchRequest) -> Any:
    connection = get_connection()
    try:
        article = articles_repo.get_article(connection, article_id)
        if article is None:
            return error_response("ARTICLE_NOT_FOUND", "기사를 찾을 수 없습니다.")
        assessment = articles_repo.get_assessment(connection, article_id)
        if assessment is None:
            classified = classify_article(
                {"title": article["title"], "description": article["description"] or ""}
            )
            with connection:
                articles_repo.upsert_assessment(
                    connection,
                    article_id=article_id,
                    assessment=classified["assessment"],
                    classifier_version=CLASSIFIER_VERSION,
                )

        patch = request.model_dump(include=request.model_fields_set)
        with connection:
            updated = articles_repo.patch_final_assessment(connection, article_id, patch)
        return ok_envelope(articles_repo.assessment_to_dict(updated))
    finally:
        connection.close()


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
