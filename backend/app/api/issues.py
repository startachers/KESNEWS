from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from backend.app.api.envelope import error_response, ok_envelope
from backend.app.repositories import article_repository as articles_repo
from backend.app.repositories import briefing_repository as briefings_repo
from backend.app.repositories import cluster_run_repository as runs_repo
from backend.app.repositories import issue_repository as issues_repo
from backend.app.repositories.database import get_connection
from backend.app.services.clustering.service import (
    ALGORITHM_VERSION,
    build_clusters,
    build_proposal,
    input_signature,
)
from backend.app.services.analysis_markdown.service import reextract_articles

router = APIRouter()


class IssuePatchRequest(BaseModel):
    editorTitle: str | None = None
    editorStatus: Literal["new", "ongoing", "expanding", "cooling", "closed"] | None = None
    editorPriority: Literal["required", "review", "reference"] | None = None
    articleId: str | None = None
    membershipAction: Literal["add", "remove"] | None = None


class ClusterRunRequest(BaseModel):
    reportDate: str
    asOf: datetime | None = None
    similarityThreshold: float = Field(default=0.40, ge=0.15, le=0.70)


class ManualGroupRequest(BaseModel):
    reportDate: str
    articleIds: list[str] = Field(min_length=2)
    expectedRevision: int


class IssueEvidencePatchRequest(BaseModel):
    expectedRevision: int = Field(ge=0)
    representativeArticleId: str | None = None
    supplementalArticleIds: list[str] = Field(default_factory=list)
    excludedArticleIds: list[str] = Field(default_factory=list)


@router.get("/api/issues")
async def list_issues(report_date: str = Query(...)) -> Any:
    connection = get_connection()
    try:
        issues = issues_repo.list_for_report_date(connection, report_date)
        briefing_states = briefings_repo.list_issue_states(connection, report_date)
        canonical_article_top_issue_ids = (
            briefings_repo.list_canonical_issue_ids_for_article_top_tags(
                connection, report_date
            )
        )
        briefing = briefings_repo.get_by_date(connection, report_date)
        for issue in issues:
            issue_state = briefing_states.get(
                issue["id"],
                {
                    "selected": False,
                    "starred": False,
                    "note": "",
                    "sortOrder": None,
                    "editorDirectCoverage": None,
                },
            )
            issue.update(issue_state)
            issue["autoDirectCoverage"] = bool(issue["directMention"])
            override = issue_state.get("editorDirectCoverage")
            if override is None and briefing is not None:
                override = briefings_repo.direct_coverage_override_for_issue(
                    connection, briefing["id"], issue["id"]
                )
                issue["editorDirectCoverage"] = override
            issue["directCoverage"] = (
                override if override is not None else issue["autoDirectCoverage"]
            )
            if (
                not issue["directCoverage"]
                and issue["id"] in canonical_article_top_issue_ids
            ):
                issue["selected"] = True
            evidence = issues_repo.list_evidence_articles(connection, issue["id"])
            issue["evidenceArticles"] = evidence["articles"] if evidence else []
    finally:
        connection.close()
    return ok_envelope({"issues": issues})


@router.get("/api/issues/{issue_id}/articles")
async def list_issue_articles(issue_id: str) -> Any:
    connection = get_connection()
    try:
        result = issues_repo.list_evidence_articles(connection, issue_id)
    finally:
        connection.close()
    if result is None:
        return error_response("ISSUE_NOT_FOUND", "이슈를 찾을 수 없습니다.")
    return ok_envelope(result)


def _reextract_issue_articles(issue_id: str) -> dict[str, Any] | None:
    connection = get_connection()
    try:
        articles = issues_repo.list_articles_for_extraction(connection, issue_id)
        if articles is None:
            return None
        with connection:
            prepared, failures = reextract_articles(connection, articles)
            changed_issue_ids: set[str] = set()
            for article in prepared:
                changed_issue_ids.update(
                    issues_repo.refresh_auto_representatives_for_article(
                        connection, article["id"]
                    )
                )
        evidence = issues_repo.list_evidence_articles(connection, issue_id)
        return {
            "issueId": issue_id,
            "requestedCount": len(articles),
            "succeededCount": len(prepared),
            "failedCount": len(failures),
            "failures": failures,
            "changedIssueIds": sorted(changed_issue_ids),
            "articles": evidence["articles"] if evidence else [],
        }
    finally:
        connection.close()


@router.post("/api/issues/{issue_id}/articles/reextract")
async def reextract_issue_articles(issue_id: str) -> Any:
    result = await asyncio.to_thread(_reextract_issue_articles, issue_id)
    if result is None:
        return error_response("ISSUE_NOT_FOUND", "이슈를 찾을 수 없습니다.")
    return ok_envelope(result)


@router.patch("/api/issues/{issue_id}/evidence")
async def patch_issue_evidence(issue_id: str, request: IssueEvidencePatchRequest) -> Any:
    connection = get_connection()
    try:
        try:
            with connection:
                result = issues_repo.update_evidence_selection(
                    connection,
                    issue_id,
                    expected_revision=request.expectedRevision,
                    representative_article_id=request.representativeArticleId,
                    supplemental_article_ids=request.supplementalArticleIds,
                    excluded_article_ids=request.excludedArticleIds,
                )
        except LookupError:
            return error_response("ISSUE_NOT_FOUND", "이슈를 찾을 수 없습니다.")
        except RuntimeError:
            return error_response(
                "ISSUE_EVIDENCE_REVISION_CONFLICT",
                "다른 화면에서 관련기사 근거 구성이 변경됐습니다.",
            )
        except PermissionError as exc:
            return error_response(
                "ARTICLE_ANALYSIS_INELIGIBLE",
                "AI 분석 부적격 기사는 대표기사나 보조근거로 지정할 수 없습니다.",
                {"articleId": str(exc)},
            )
        except ValueError as exc:
            if str(exc) == "supplemental_limit":
                return error_response(
                    "SUPPLEMENTAL_ARTICLE_LIMIT_EXCEEDED",
                    "보조근거는 이슈당 최대 2건까지 지정할 수 있습니다.",
                )
            return error_response("ISSUE_EVIDENCE_INVALID", "관련기사 근거 구성이 올바르지 않습니다.")
    finally:
        connection.close()
    return ok_envelope(result)


@router.patch("/api/issues/{issue_id}")
async def patch_issue(issue_id: str, request: IssuePatchRequest) -> Any:
    connection = get_connection()
    try:
        if issues_repo.get(connection, issue_id) is None:
            return error_response("ISSUE_NOT_FOUND", "이슈를 찾을 수 없습니다.")
        fields = request.model_dump(include={"editorTitle", "editorStatus", "editorPriority"})
        fields = {key: value for key, value in fields.items() if key in request.model_fields_set}
        if request.articleId or request.membershipAction:
            if not request.articleId or not request.membershipAction:
                return error_response(
                    "ISSUE_MEMBERSHIP_INVALID", "articleId와 membershipAction을 함께 지정해야 합니다."
                )
            if articles_repo.get_article(connection, request.articleId) is None:
                return error_response("ARTICLE_NOT_FOUND", "기사를 찾을 수 없습니다.")
        with connection:
            issues_repo.patch_editor(connection, issue_id, fields)
            if request.articleId and request.membershipAction:
                issues_repo.set_membership_override(
                    connection, issue_id, request.articleId, request.membershipAction
                )
            report_date = issues_repo.report_date_for_issue(connection, issue_id)
            if report_date:
                issues_repo.recalculate_review_assessments(connection, report_date)
        return ok_envelope(issues_repo.serialize_one(connection, issue_id))
    finally:
        connection.close()


@router.post("/api/issues/manual-group")
async def create_manual_group(request: ManualGroupRequest) -> Any:
    article_ids = list(dict.fromkeys(request.articleIds))
    if len(article_ids) < 2:
        return error_response(
            "ISSUE_MANUAL_GROUP_INVALID", "서로 다른 기사를 2건 이상 선택해야 합니다."
        )
    connection = get_connection()
    try:
        candidate_ids = articles_repo.list_candidate_article_ids(connection, request.reportDate)
        if not set(article_ids).issubset(candidate_ids):
            return error_response(
                "ISSUE_MANUAL_GROUP_INVALID", "현재 보고일의 기사만 묶을 수 있습니다."
            )
        with connection:
            issue_id = issues_repo.create_manual_group(
                connection, request.reportDate, article_ids
            )
            briefing = briefings_repo.patch_issue_state(
                connection,
                request.reportDate,
                issue_id,
                request.expectedRevision,
                {},
            )
            issues_repo.recalculate_review_assessments(connection, request.reportDate)
            issue = issues_repo.serialize_one(connection, issue_id)
    except briefings_repo.BriefingNotFound:
        return error_response("BRIEFING_NOT_FOUND", "작업본을 찾을 수 없습니다.")
    except briefings_repo.BriefingFinalized:
        return error_response("BRIEFING_FINALIZED", "최종 확정된 작업본은 수정할 수 없습니다.")
    except briefings_repo.RevisionConflict:
        return error_response(
            "BRIEFING_REVISION_CONFLICT", "다른 화면에서 브리핑이 변경됐습니다."
        )
    finally:
        connection.close()
    return ok_envelope({"issue": issue, "revision": briefing["revision"]})


@router.post("/api/cluster-runs")
async def create_cluster_run(request: ClusterRunRequest) -> Any:
    connection = get_connection()
    try:
        articles = issues_repo.clustering_input(connection, request.reportDate)
        as_of = request.asOf or datetime.now(timezone.utc)
        if as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=timezone.utc)
        else:
            as_of = as_of.astimezone(timezone.utc)
        clusters = build_clusters(articles, as_of, request.similarityThreshold)
        proposal, diff = build_proposal(clusters, issues_repo.matching_state(connection))
        with connection:
            row = runs_repo.create(
                connection,
                report_date=request.reportDate,
                input_signature=input_signature(articles),
                proposal=proposal,
                diff=diff,
                algorithm_version=ALGORITHM_VERSION,
            )
        return ok_envelope(runs_repo.serialize(row))
    finally:
        connection.close()


@router.get("/api/cluster-runs/{cluster_run_id}")
async def get_cluster_run(cluster_run_id: str) -> Any:
    connection = get_connection()
    try:
        row = runs_repo.get(connection, cluster_run_id)
    finally:
        connection.close()
    if row is None:
        return error_response("CLUSTER_RUN_NOT_FOUND", "군집 실행을 찾을 수 없습니다.")
    return ok_envelope(runs_repo.serialize(row))


@router.post("/api/cluster-runs/{cluster_run_id}/apply")
async def apply_cluster_run(cluster_run_id: str) -> Any:
    connection = get_connection()
    try:
        run = runs_repo.get(connection, cluster_run_id)
        if run is None:
            return error_response("CLUSTER_RUN_NOT_FOUND", "군집 실행을 찾을 수 없습니다.")
        if run["status"] == "applied":
            return ok_envelope(runs_repo.serialize(run))
        briefing = briefings_repo.get_by_date(connection, run["report_date"])
        if briefing is not None and briefing["status"] == "final":
            return error_response("BRIEFING_FINALIZED", "최종 확정된 작업본에는 재군집화를 적용할 수 없습니다.")
        articles = issues_repo.clustering_input(connection, run["report_date"])
        if input_signature(articles) != run["input_signature"]:
            return error_response(
                "CLUSTER_RUN_STALE", "proposal 생성 후 기사 후보가 변경됐습니다. 다시 군집화해 주세요."
            )
        serialized = runs_repo.serialize(run)
        with connection:
            issue_ids = issues_repo.apply_proposal(connection, cluster_run_id, serialized["proposal"])
            issues_repo.apply_review_assessments(
                connection, run["report_date"], serialized["proposal"], issue_ids
            )
            runs_repo.mark_applied(connection, cluster_run_id)
            briefings_repo.normalize_direct_coverage(connection, run["report_date"])
        applied = runs_repo.get(connection, cluster_run_id)
        return ok_envelope(runs_repo.serialize(applied))
    finally:
        connection.close()
