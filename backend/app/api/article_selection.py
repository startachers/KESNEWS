from __future__ import annotations

import asyncio
import time
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from backend.app.api.analysis import ANALYSIS_TIMEOUT_SECONDS, _context_length
from backend.app.api.envelope import error_response, ok_envelope
from backend.app.repositories import ai_selection_repository as selection_repo
from backend.app.repositories import article_repository as articles_repo
from backend.app.repositories import briefing_repository as briefings_repo
from backend.app.repositories import issue_repository as issues_repo
from backend.app.repositories import press_release_repository as press_release_repo
from backend.app.repositories.database import get_connection
from backend.app.services.ai.article_selection import (
    MAX_SELECTED_ARTICLES,
    PROMPT_VERSION,
    TOPIC_GROUP_LABELS,
    SelectionError,
    build_candidate_input,
    input_signature,
    recommend,
    preferred_topic_groups,
)
from backend.app.services.ai.ollama_client import OllamaError, default_client
from backend.app.services.ai.runtime import AnalysisCancelled, CancellationToken, analysis_registry
from backend.app.services.classification.origin import assess_kesco_origin

router = APIRouter()


class RecommendRequest(BaseModel):
    expectedRevision: int
    model: str


class ApplyRequest(BaseModel):
    expectedRevision: int
    runId: str


def _selection_input(connection, report_date: str, model: str):
    articles = articles_repo.list_candidates(connection, report_date, include_dismissed=False)
    releases = press_release_repo.list_recent(connection)
    articles = [
        article
        if article.get("origin") is not None
        else _with_inferred_origin(article, releases)
        for article in articles
    ]
    issues = issues_repo.list_for_report_date(connection, report_date)
    briefing = briefings_repo.get_by_date(connection, report_date)
    if briefing is not None:
        excluded_ids = {
            article_id
            for issue in issues
            if briefings_repo.is_direct_coverage_issue(
                connection, briefing["id"], issue["id"]
            )
            for article_id in issue.get("articleIds") or []
        }
        articles = [
            article for article in articles
            if article["id"] not in excluded_ids and not article.get("directCoverage")
        ]
    selected_ids = [str(item["id"]) for item in articles if item.get("included")]
    candidates, evidence = build_candidate_input(articles, issues)
    target_count = min(
        max(0, MAX_SELECTED_ARTICLES - len(selected_ids)),
        len(candidates),
    )
    preferred_groups = preferred_topic_groups(articles, candidates, target_count)
    signature = input_signature(
        model, target_count, selected_ids, candidates, preferred_groups
    )
    return selected_ids, candidates, evidence, target_count, preferred_groups, signature


def _with_inferred_origin(
    article: dict[str, Any], releases: list[dict[str, Any]]
) -> dict[str, Any]:
    match = assess_kesco_origin(article, releases)
    if match is None:
        return article
    return {
        **article,
        "origin": {
            "effectiveType": match["originType"],
            "pressReleaseId": match["pressReleaseId"],
            "confidence": match["confidence"],
            "reasons": match.get("reasons") or {},
            "inferredForSelection": True,
        },
    }


def _latest_success(connection, briefing_id: str) -> dict[str, Any] | None:
    return selection_repo.serialize(selection_repo.latest_success(connection, briefing_id))


@router.post("/api/briefings/{report_date}/selection-recommendations")
async def create_selection_recommendations(
    report_date: str, body: RecommendRequest, request: Request
) -> Any:
    active_run_id = analysis_registry.active_run_id()
    if active_run_id is not None:
        return error_response(
            "AI_ALREADY_RUNNING",
            "다른 AI 분석이 이미 실행 중입니다. 완료하거나 취소한 뒤 다시 시도해 주세요.",
            {"runId": active_run_id},
        )
    client = getattr(request.app.state, "ollama_client", default_client)
    context_length = _context_length(client, body.model)
    connection = get_connection()
    registered = False
    try:
        briefing = briefings_repo.get_by_date(connection, report_date)
        if briefing is None:
            return error_response("BRIEFING_NOT_FOUND", f"{report_date} 작업본이 없습니다.")
        if briefing["status"] == "final":
            return error_response("BRIEFING_FINALIZED", "최종 확정된 작업본은 변경할 수 없습니다.")
        if briefing["revision"] != body.expectedRevision:
            return error_response("BRIEFING_REVISION_CONFLICT", "다른 화면에서 브리핑이 변경됐습니다.")
        selected_ids, candidates, evidence, target_count, preferred_groups, signature = _selection_input(
            connection, report_date, body.model
        )
        if target_count == 0:
            message = "이미 12건 이상 선정되어 있습니다." if len(selected_ids) >= MAX_SELECTED_ARTICLES else "추천할 미선정 후보가 없습니다."
            return error_response("AI_SELECTION_NOT_NEEDED", message)
        request_snapshot = {
            "reportDate": report_date,
            "selectedArticleIds": selected_ids,
            "targetCount": target_count,
            "candidateCount": len(candidates),
            "candidates": candidates,
            "preferredTopicGroups": preferred_groups,
            "preferredTopicLabels": [
                TOPIC_GROUP_LABELS[group] for group in preferred_groups
            ],
            "contextLength": context_length,
        }
        connection.execute("BEGIN IMMEDIATE")
        run = selection_repo.create(
            connection,
            briefing_id=briefing["id"],
            model=body.model,
            prompt_version=PROMPT_VERSION,
            input_signature=signature,
            request=request_snapshot,
            evidence=evidence,
        )
        run_id = run["id"]
        briefing_id = briefing["id"]
        cancel_token = CancellationToken()
        if not analysis_registry.register(run_id, briefing_id, cancel_token):
            connection.rollback()
            return error_response("AI_ALREADY_RUNNING", "다른 AI 분석이 이미 실행 중입니다.")
        registered = True
        connection.commit()
    except Exception:
        connection.rollback()
        if registered:
            analysis_registry.unregister(run_id)
        raise
    finally:
        connection.close()

    try:
        worker = asyncio.create_task(asyncio.to_thread(
            recommend,
            client,
            model=body.model,
            report_date=report_date,
            target_count=target_count,
            candidates=candidates,
            evidence=evidence,
            preferred_groups=preferred_groups,
            cancel_token=cancel_token,
        ))
        deadline = time.monotonic() + ANALYSIS_TIMEOUT_SECONDS
        while not worker.done():
            await asyncio.wait({worker}, timeout=0.25)
            if time.monotonic() >= deadline:
                cancel_token.cancel("timeout")
            elif await request.is_disconnected():
                cancel_token.cancel("client_disconnected")
        output = await worker
    except AnalysisCancelled as exc:
        code = "AI_TIMEOUT" if exc.reason == "timeout" else "AI_CANCELLED"
        stored = f"{code}: 기사 추천 실행이 중단됐습니다."
        connection = get_connection()
        try:
            with connection:
                selection_repo.finish_failed(connection, run_id, stored)
            latest = _latest_success(connection, briefing_id)
        finally:
            connection.close()
        return error_response(code, "기사 추천 실행을 중단했습니다.", {"lastSuccessfulRun": latest})
    except SelectionError as exc:
        connection = get_connection()
        try:
            with connection:
                selection_repo.finish_failed(
                    connection, run_id, f"{exc.code}: {exc}",
                    {"raw": exc.raw_response, "attempts": exc.attempts},
                )
            latest = _latest_success(connection, briefing_id)
        finally:
            connection.close()
        return error_response(exc.code, str(exc), {"lastSuccessfulRun": latest})
    except (OllamaError, OSError, TimeoutError) as exc:
        connection = get_connection()
        try:
            with connection:
                selection_repo.finish_failed(connection, run_id, f"AI_UNAVAILABLE: {exc}")
            latest = _latest_success(connection, briefing_id)
        finally:
            connection.close()
        return error_response("AI_UNAVAILABLE", "Ollama에 연결할 수 없습니다.", {"lastSuccessfulRun": latest})
    finally:
        analysis_registry.unregister(run_id)
        unload = getattr(client, "unload_model", None)
        if callable(unload):
            try:
                await asyncio.to_thread(unload, body.model)
            except (OllamaError, OSError, TimeoutError):
                pass

    connection = get_connection()
    try:
        current = briefings_repo.get_by_date(connection, report_date)
        _, _, _, current_target, current_preferred_groups, current_signature = _selection_input(
            connection, report_date, body.model
        )
        if (
            current is None
            or current["revision"] != body.expectedRevision
            or current_target != target_count
            or current_preferred_groups != preferred_groups
            or current_signature != signature
        ):
            with connection:
                selection_repo.finish_failed(connection, run_id, "AI_INPUT_STALE: 추천 중 기사 상태가 변경됐습니다.")
            return error_response("AI_INPUT_STALE", "추천 중 기사 상태가 변경되어 결과를 저장하지 않았습니다.")
        recommendations = []
        by_evidence = {item["id"]: item for item in candidates}
        for item in sorted(output.result["recommendations"], key=lambda value: value["rank"]):
            candidate = by_evidence[item["evidenceId"]]
            recommendations.append({
                **item,
                "articleId": evidence[item["evidenceId"]],
                "title": candidate["title"],
                "source": candidate["source"],
            })
        response_payload = {
            "recommendations": recommendations,
            "limitations": output.result.get("limitations") or [],
            "attempts": output.attempts,
        }
        with connection:
            stored = selection_repo.finish_success(connection, run_id, response_payload)
        return ok_envelope({"run": selection_repo.serialize(stored)})
    finally:
        connection.close()


@router.post("/api/briefings/{report_date}/selection-recommendations/apply")
async def apply_selection_recommendations(report_date: str, body: ApplyRequest) -> Any:
    connection = get_connection()
    try:
        briefing = briefings_repo.get_by_date(connection, report_date)
        if briefing is None:
            return error_response("BRIEFING_NOT_FOUND", f"{report_date} 작업본이 없습니다.")
        run = selection_repo.get(connection, body.runId)
        if run is None or run["briefing_id"] != briefing["id"]:
            return error_response("AI_SELECTION_RUN_NOT_FOUND", "기사 추천 실행을 찾을 수 없습니다.")
        if run["status"] != "success":
            return error_response("AI_SELECTION_RUN_NOT_APPLICABLE", "적용 가능한 추천 결과가 아닙니다.")
        if briefing["revision"] != body.expectedRevision:
            return error_response("BRIEFING_REVISION_CONFLICT", "다른 화면에서 브리핑이 변경됐습니다.")
        _, _, _, _, _, signature = _selection_input(connection, report_date, run["model"])
        if signature != run["input_signature"]:
            return error_response("AI_INPUT_STALE", "기사 상태가 변경되어 추천을 다시 실행해야 합니다.")
        serialized = selection_repo.serialize(run)
        article_ids = [item["articleId"] for item in serialized["response"]["recommendations"]]
        with connection:
            (
                updated,
                applied_ids,
                top_issue_issue_ids,
                top_issue_article_ids,
                top_issue_count,
            ) = briefings_repo.apply_ai_recommendations(
                connection, report_date, body.expectedRevision, article_ids
            )
            selection_repo.mark_applied(connection, body.runId)
    except briefings_repo.BriefingFinalized:
        return error_response("BRIEFING_FINALIZED", "최종 확정된 작업본은 변경할 수 없습니다.")
    except briefings_repo.RevisionConflict:
        return error_response("BRIEFING_REVISION_CONFLICT", "다른 화면에서 브리핑이 변경됐습니다.")
    finally:
        connection.close()
    return ok_envelope(
        {
            "runId": body.runId,
            "appliedArticleIds": applied_ids,
            "topIssueIssueIds": top_issue_issue_ids,
            "topIssueArticleIds": top_issue_article_ids,
            "activatedTopIssueCount": len(top_issue_issue_ids) + len(top_issue_article_ids),
            "topIssueCount": top_issue_count,
            "selectedCount": min(
                MAX_SELECTED_ARTICLES,
                len(applied_ids) + len(serialized["request"]["selectedArticleIds"]),
            ),
            "revision": updated["revision"],
        },
        meta={"revision": updated["revision"]},
    )
