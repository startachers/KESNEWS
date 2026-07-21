from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.app.core.clock import now_iso
from backend.app.repositories import article_repository as article_repo
from backend.app.repositories import analysis_markdown_repository as markdown_repo
from backend.app.repositories import issue_repository as issue_repo
from backend.app.services.analysis_markdown import budget, builder, quality, storage
from backend.app.services.analysis_markdown.config import load_config
from backend.app.services.analysis_markdown.eligibility import evaluate
from backend.app.services.analysis_markdown.replacement_finder import (
    find_replacement,
    search_trusted_candidates,
)
from backend.app.services.analysis_markdown.signature import content_hash, input_signature
from backend.app.services.analysis_markdown.source import build_source_context
from backend.app.services.extraction.article_body import fetch_article_body_with_retries
from backend.app.services.extraction.cleaner import clean_article_text
from backend.app.services.extraction.evidence_quality import assess
from backend.app.services.extraction.evidence_validation import serialize_errors, validate_source
from backend.app.services.ids import make_id
from backend.app.services.normalization.url import canonical_article_url


class GenerationError(ValueError):
    def __init__(self, code: str, message: str, details: list[dict] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or []


@dataclass(frozen=True)
class GenerationOutput:
    content: str
    result: dict[str, Any]


def _prepare(article: dict, config: dict, *, allow_network: bool) -> dict:
    raw = article.get("bodyText") or ""
    status = "success_full" if raw else "failed"
    attempts: tuple[dict[str, str], ...] = ()
    resolved_url = article.get("url") or ""
    stored_canonical = article.get("canonicalUrl") or ""
    canonical_url = stored_canonical if str(stored_canonical).startswith(("http://", "https://")) else ""
    page_publisher = ""
    if not raw and article.get("description"):
        raw = article["description"]
        status = "success_summary"
        attempts = ({"stage": "official_rss", "status": "success"},)
    cleaning = clean_article_text(raw, title=article.get("title") or "")
    eligibility = evaluate(cleaning, status=status, url=resolved_url, config=config)
    if allow_network and (not eligibility.eligible or status != "success_full") and article.get("url"):
        def acceptable_body(body: str, body_url: str) -> bool:
            candidate_cleaning = clean_article_text(body, title=article.get("title") or "")
            return evaluate(
                candidate_cleaning, status="success_full", url=body_url, config=config
            ).eligible

        fetched = fetch_article_body_with_retries(
            article["url"], body_validator=acceptable_body
        )
        attempts = fetched.attempts
        if fetched.body_text:
            fetched_cleaning = clean_article_text(fetched.body_text, title=article.get("title") or "")
            fetched_eligibility = evaluate(
                fetched_cleaning, status=fetched.status, url=fetched.resolved_url or resolved_url,
                config=config,
            )
            if fetched_eligibility.eligible or not eligibility.eligible:
                raw, status, cleaning, eligibility = (
                    fetched.body_text, fetched.status, fetched_cleaning, fetched_eligibility
                )
                resolved_url = fetched.resolved_url or resolved_url
                canonical_url = fetched.canonical_url or canonical_url
                page_publisher = fetched.page_publisher or ""
        elif not eligibility.eligible:
            status = "failed"
            eligibility = type(eligibility)(False, fetched.error or eligibility.reason, "none")
    source_validation = validate_source(
        raw_source=article.get("rawSource") or article.get("source") or "",
        displayed_source=article.get("source") or "",
        source_url=article.get("url") or "",
        resolved_url=resolved_url,
        canonical_url=canonical_url,
        page_publisher=page_publisher,
    )
    result = {**article, "source": source_validation.source}
    method = (attempts[-1].get("stage") if attempts else None) or (
        "stored_body" if status == "success_full" else "rss_summary" if status == "success_summary" else "none"
    )
    quality_result = assess(
        {
            **article, "source": source_validation.source, "rawText": raw,
            "url": source_validation.canonical_url or source_validation.resolved_url,
            "sourceValidationErrors": list(source_validation.errors),
        }, cleaning,
        status=status, method=method, config=config,
    )
    result.update({
        "rawText": raw, "cleanedText": cleaning.text, "status": status,
        "url": source_validation.canonical_url or source_validation.resolved_url,
        "failureReason": "" if eligibility.eligible else eligibility.reason,
        "analysisEligible": quality_result["analysisEligible"],
        "rawCharacterCount": len(raw), "cleanedCharacterCount": len(cleaning.text),
        "attempts": list(attempts), "resolvedUrl": resolved_url,
        "noiseDetected": cleaning.noise_detected,
        "aiContentDetected": cleaning.ai_content_detected,
        "cleaningRuleVersion": config["cleaning_rule_version"],
        "canonicalUrl": source_validation.canonical_url,
        "pagePublisher": source_validation.page_publisher,
        "sourceDomain": source_validation.source_domain,
        "rawSource": source_validation.raw_source,
        "normalizedSource": source_validation.source,
        "normalizationReason": source_validation.normalization_reason,
        **quality_result,
    })
    result["status"] = quality_result["extractionStatus"]
    if result.get("validationErrors"):
        result["failureReason"] = result["validationErrors"][0]
    if not result["analysisEligible"] and not result["failureReason"]:
        blocking_reasons = {
            "문장 종료 불완전", "완전한 문장 부족", "언론사 확인 불가",
            "보도 시각 확인 불가", "신뢰 언론사 허용목록 제외",
        }
        result["failureReason"] = next(
            (reason for reason in result["qualityReasons"] if reason in blocking_reasons),
            "quality_below_threshold",
        )
    return result


def _issue_maps(connection: sqlite3.Connection, report_date: str) -> tuple[dict[str, set[str]], dict[str, list[dict]]]:
    ids: dict[str, set[str]] = {}
    details: dict[str, list[dict]] = {}
    for issue in issue_repo.list_for_report_date(connection, report_date):
        item = {"id": issue["id"], "title": issue.get("effectiveTitle") or issue.get("autoTitle") or ""}
        for article_id in issue.get("articleIds") or []:
            details.setdefault(article_id, []).append(item)
            # 자동 군집만으로 대체기사를 확정하지 않는다. 담당자의 제목/우선도/구성
            # override 또는 수동 군집이 있는 경우에만 확정 군집 근거로 사용한다.
            if (
                issue.get("manualGroup")
                or issue.get("editorTitle")
                or issue.get("editorPriority")
                or issue.get("membershipOverrides")
            ):
                ids.setdefault(article_id, set()).add(issue["id"])
    return ids, details


def _save_extraction(
    connection: sqlite3.Connection, article: dict, *, replacement_article_id: str | None = None,
    replaces_article_id: str | None = None, same_issue_id: str | None = None,
) -> None:
    connection.execute(
        """INSERT INTO article_extractions (
               id, article_id, source_url, resolved_url, raw_text, cleaned_text,
               extraction_status, failure_reason, analysis_eligible, raw_character_count,
               cleaned_character_count, extraction_attempts_json, replacement_article_id,
               replaces_article_id, same_issue_id, cleaning_rule_version, created_at,
               content_quality_score, quality_grade, quality_reasons_json,
               complete_sentence_count, contamination_flags_json, extraction_method,
               canonical_url, page_publisher, source_domain, raw_source, normalized_source,
               normalization_reason, validation_errors_json
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            make_id(), article["id"], article.get("url"), article.get("resolvedUrl"),
            article.get("rawText"), article.get("cleanedText"), article["status"],
            article.get("failureReason") or None, int(article["analysisEligible"]),
            article["rawCharacterCount"], article["cleanedCharacterCount"],
            json.dumps(article.get("attempts") or [], ensure_ascii=False, sort_keys=True),
            replacement_article_id, replaces_article_id, same_issue_id,
            article["cleaningRuleVersion"], now_iso(), article.get("contentQualityScore"),
            article.get("qualityGrade"),
            json.dumps(article.get("qualityReasons") or [], ensure_ascii=False),
            article.get("completeSentenceCount", 0),
            json.dumps(article.get("contaminationFlags") or [], ensure_ascii=False),
            article.get("extractionMethod"),
            article.get("canonicalUrl"), article.get("pagePublisher"),
            article.get("sourceDomain"), article.get("rawSource"),
            article.get("normalizedSource"), article.get("normalizationReason"),
            json.dumps(article.get("validationErrors") or [], ensure_ascii=False),
        ),
    )


def reextract_article(connection: sqlite3.Connection, article: dict[str, Any]) -> dict[str, Any]:
    """기사 한 건을 다시 추출하고 원문과 불변 추출 이력을 함께 갱신한다."""
    config = load_config()
    prepared = _prepare(article, config, allow_network=True)
    _persist_reextraction(connection, article, prepared)
    return prepared


def _persist_reextraction(
    connection: sqlite3.Connection,
    article: dict[str, Any],
    prepared: dict[str, Any],
) -> None:
    _save_extraction(connection, prepared)
    quality.record_event(connection, prepared, prepared)
    if prepared["status"] == "success_full" and prepared.get("rawText"):
        article_repo.update_article_body(
            connection,
            article["id"],
            body_text=prepared["rawText"],
            body_status="full_text",
            body_error="",
        )
    if not set(prepared.get("validationErrors") or []).intersection(
        {"publisher_identity_mismatch", "canonical_url_unresolved"}
    ):
        article_repo.update_verified_source(
            connection,
            article["id"],
            source=prepared.get("normalizedSource") or article.get("source") or "",
            source_domain=prepared.get("sourceDomain") or "",
            canonical_url=prepared.get("canonicalUrl") or prepared.get("resolvedUrl") or "",
        )
    elif prepared["status"] == "failed":
        article_repo.update_article_body(
            connection,
            article["id"],
            body_text=article.get("bodyText") or "",
            body_status=article.get("bodyStatus") or "missing",
            body_error=prepared.get("failureReason") or "본문 추출 실패",
        )


def reextract_articles(
    connection: sqlite3.Connection,
    articles: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """관련기사 전체를 동시에 추출한 뒤 결과를 한 DB transaction에 기록한다."""
    if not articles:
        return [], []
    config = load_config()
    prepared: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=len(articles)) as executor:
        futures = [
            (article, executor.submit(_prepare, article, config, allow_network=True))
            for article in articles
        ]
        for article, future in futures:
            try:
                result = future.result()
                connection.execute("SAVEPOINT reextract_article")
                _persist_reextraction(connection, article, result)
                connection.execute("RELEASE SAVEPOINT reextract_article")
            except Exception as exc:  # 한 언론사 실패가 나머지 기사 결과를 버리지 않게 분리한다.
                try:
                    connection.execute("ROLLBACK TO SAVEPOINT reextract_article")
                    connection.execute("RELEASE SAVEPOINT reextract_article")
                except sqlite3.OperationalError:
                    pass
                failures.append({"articleId": article["id"], "message": str(exc)})
                continue
            prepared.append(result)
    return prepared, failures


def _persist_searched_article(
    connection: sqlite3.Connection, article: dict, *, original_article_id: str
) -> dict:
    resolved_url = article.get("resolvedUrl") or article.get("url") or ""
    canonical_url = canonical_article_url(resolved_url)
    existing = (
        connection.execute(
            "SELECT * FROM articles WHERE canonical_url = ?", (canonical_url,)
        ).fetchone()
        if canonical_url
        else None
    )
    if existing is not None and existing["id"] != original_article_id:
        article["id"] = existing["id"]
        return article
    article["id"] = article_repo.create_article(
        connection,
        url=resolved_url,
        title=article.get("title") or "제목 없음",
        source=article.get("source"),
        published_at=article.get("pubDate"),
        description=article.get("description"),
        category_hint=article.get("category"),
        manual=False,
        publisher_id=article.get("publisherId"),
        publisher_allowed=True,
    )
    article_repo.insert_observation(
        connection,
        article_id=article["id"],
        collection_run_provider_id=None,
        provider="Google 뉴스 RSS (대체기사 탐색)",
        provider_item_key=None,
        query_group_id=None,
        raw_url=article.get("url"),
        raw_title=article.get("title"),
        raw_source=article.get("source"),
        raw_published_at=article.get("pubDate"),
        raw_description=article.get("description"),
        raw_payload_json=None,
        dedup_method="replacement_search",
        dedup_score=None,
    )
    return article


def _signature_payload(
    *, report_date: str, prepared_by: str, selected: list[dict], included: list[dict],
    weather: dict | None, config: dict,
) -> dict:
    included_by_original = {item.get("originalArticleId") or item["id"]: item for item in included}
    rows = []
    for article in selected:
        effective = included_by_original.get(article["id"])
        rows.append({
            "originalArticleId": article["id"],
            "replacementArticleId": effective["id"] if effective and effective["id"] != article["id"] else None,
            "title": article.get("title") or "", "source": article.get("source") or "",
            "publishedAt": article.get("pubDate"), "url": article.get("url") or "",
            "rawTextOrSummary": (effective or article).get("rawText") or article.get("description") or "",
            "status": (effective or article).get("status") or article.get("bodyStatus"),
            "note": article.get("note") or "", "priority": article.get("priority"),
            "category": article.get("category"), "risk": article.get("risk"),
            "analysisEligible": bool(effective),
        })
    return {
        "documentVersion": config["version"],
        "cleaningRuleVersion": config["cleaning_rule_version"],
        "reportDate": report_date, "preparedBy": prepared_by,
        "articles": rows, "weather": weather,
        "lengthBudget": {
            "article": config["article_character_limits"], "document": config["document_budget"]
        },
        "publisherQuality": config["publisher_quality"],
        "disabledPublishers": config.get("disabled_publishers") or [],
    }


def _fit_document(render, articles: list[dict], excluded: list[dict], config: dict) -> str:
    maximum = int(config["document_budget"]["max_characters"])
    content = render()
    if len(content) <= maximum:
        return content
    for priority in ("reference", "review"):
        for article in sorted(
            [item for item in articles if item.get("priority") == priority],
            key=lambda item: (item.get("priorityScore") or 0, item["id"]),
        ):
            articles.remove(article)
            excluded.append({
                "articleId": article["id"],
                "priority": priority,
                "reason": "document_budget",
                "rawCharacterCount": article.get("rawCharacterCount", 0),
                "cleanedCharacterCount": article.get("cleanedCharacterCount", 0),
            })
            content = render()
            if len(content) <= maximum:
                return content
    for article in [item for item in articles if item.get("priority") == "required"]:
        reduced, changed = budget.truncate_at_sentence(article["includedText"], 500)
        if changed and reduced:
            article["includedText"] = reduced
            article["includedCharacterCount"] = len(reduced)
            article["truncated"] = True
            content = render()
            if len(content) <= maximum:
                return content
    raise GenerationError("DOCUMENT_BUDGET_EXCEEDED", "정상 축소 절차로 문서 예산을 충족하지 못했습니다.")


def generate(
    connection_factory, report_date: str, *, save: bool = True, validation: bool = False,
    allow_network: bool = True, config_path: Path | None = None,
) -> GenerationOutput:
    config = load_config(config_path) if config_path else load_config()
    connection = connection_factory()
    try:
        source_context = build_source_context(connection, report_date, config)
        if source_context is None:
            raise GenerationError("BRIEFING_NOT_FOUND", f"{report_date} 작업본이 없습니다.")
        briefing = source_context.briefing
        start_revision = int(briefing["revision"])
        start_source_signature = source_context.signature
        prepared_by = briefing["prepared_by"] or ""
        candidates = article_repo.list_candidates(connection, report_date, include_dismissed=False)
        selected = source_context.exchange.articles
        missing_required_issues = source_context.missing_required_issues
        issue_ids, issue_details = _issue_maps(connection, report_date)
        weather = source_context.weather
    finally:
        connection.close()
    if missing_required_issues:
        raise GenerationError(
            "REQUIRED_ARTICLE_EVIDENCE_MISSING",
            f"필수 보고 이슈 {len(missing_required_issues)}건의 대표 근거 기사를 확보하지 못했습니다.",
            list(missing_required_issues),
        )
    if not selected:
        raise GenerationError("NO_ELIGIBLE_ARTICLES", "분석할 선정 기사가 없습니다.")

    with ThreadPoolExecutor(max_workers=min(8, len(selected))) as executor:
        prepared = list(executor.map(lambda item: _prepare(item, config, allow_network=allow_network), selected))
    prepared_by_id = {item["id"]: item for item in prepared}
    local_candidates = [
        _prepare(item, config, allow_network=False)
        for item in candidates if item["id"] not in prepared_by_id
    ]
    all_prepared = prepared + local_candidates

    connection = connection_factory()
    try:
        with connection:
            for article in prepared:
                _save_extraction(connection, article)
                quality.record_event(connection, article, article)
                if not set(article.get("validationErrors") or []).intersection(
                    {"publisher_identity_mismatch", "canonical_url_unresolved"}
                ):
                    article_repo.update_verified_source(
                        connection, article["id"], source=article.get("normalizedSource") or article.get("source") or "",
                        source_domain=article.get("sourceDomain") or "",
                        canonical_url=article.get("canonicalUrl") or article.get("resolvedUrl") or "",
                    )
            publisher_stats = quality.publisher_statistics(connection, config)
        quarantine = {
            item["publisherId"] for item in publisher_stats if item["status"] in {"quarantine", "disabled"}
        }
    finally:
        connection.close()
    for article in all_prepared:
        if (article.get("publisherId") or article.get("source")) in quarantine:
            article["analysisEligible"] = False
            article["failureReason"] = "publisher_quarantined"

    invalid_selected = []
    for article in prepared:
        if article["analysisEligible"]:
            continue
        validation_errors = article.get("validationErrors") or []
        errors = serialize_errors(validation_errors) if validation_errors else [{
            "code": "ARTICLE_ANALYSIS_INELIGIBLE", "status": "analysis_ineligible",
            "message": "기사 근거가 현재 분석 정책을 통과하지 못했습니다.",
        }]
        invalid_selected.append({
            "articleId": article["id"], "title": article.get("title") or "",
            "issueId": article.get("issueId") or None,
            "source": article.get("source") or "", "url": article.get("url") or "",
            "errors": errors,
            "availableActions": ["관련기사 선택", "본문 다시 추출", "원문 확인"],
        })
    if invalid_selected:
        raise GenerationError(
            "SELECTED_EVIDENCE_INVALID",
            f"선택한 기사 중 근거 상태를 확인해야 하는 기사가 {len(invalid_selected)}건 있습니다.",
            invalid_selected,
        )

    included: list[dict] = []
    excluded: list[dict] = []
    replacements: list[dict] = []
    required_failures: list[dict] = []
    for original in prepared:
        if original["analysisEligible"]:
            original["originalArticleId"] = original["id"]
            original["issues"] = issue_details.get(original["id"], [])
            included.append(original)
            continue
        replacement = find_replacement(original, all_prepared, issue_ids_by_article=issue_ids)
        searched_summaries: list[dict] = []
        if replacement is None and allow_network:
            try:
                searched = search_trusted_candidates(original)
            except Exception:  # 검색 실패는 원 기사 실패 정보와 분리하고 생성 가능 여부를 계속 판정한다.
                searched = []
            searched_summaries = [
                {"title": item.get("title"), "source": item.get("source"), "url": item.get("url")}
                for item in searched[:10]
            ]
            remaining = list(searched)
            for _ in range(min(3, len(remaining))):
                provisional = [{**item, "analysisEligible": True} for item in remaining]
                candidate = find_replacement(
                    original, provisional, issue_ids_by_article=issue_ids
                )
                if candidate is None:
                    break
                raw_candidate = next(item for item in remaining if item["id"] == candidate["id"])
                prepared_candidate = _prepare(raw_candidate, config, allow_network=True)
                if prepared_candidate["analysisEligible"]:
                    connection = connection_factory()
                    try:
                        with connection:
                            replacement = _persist_searched_article(
                                connection, prepared_candidate,
                                original_article_id=original["id"],
                            )
                            replacement["searchedReplacement"] = True
                            _save_extraction(
                                connection, replacement, replaces_article_id=original["id"]
                            )
                            quality.record_event(connection, replacement, replacement)
                    finally:
                        connection.close()
                    all_prepared.append(replacement)
                    break
                remaining = [item for item in remaining if item["id"] != candidate["id"]]
        if replacement:
            replacement = dict(replacement)
            replacement["originalArticleId"] = original["id"]
            replacement["replacesArticleId"] = original["id"]
            replacement["priority"] = original.get("priority")
            replacement["note"] = original.get("note") or ""
            replacement["starred"] = original.get("starred")
            replacement["topIssue"] = original.get("topIssue")
            replacement["issues"] = issue_details.get(replacement["id"], [])
            included.append(replacement)
            same = next(iter(issue_ids.get(original["id"], set()) & issue_ids.get(replacement["id"], set())), None)
            replacements.append({
                "originalArticleId": original["id"], "replacementArticleId": replacement["id"],
                "reason": (
                    "원문 근거 미확보 후 담당자 확정 동일 이슈의 신뢰 언론사 기사 사용"
                    if same
                    else "원문 근거 미확보 후 날짜·기관·장소·핵심 명사를 대조한 신뢰 언론사 기사 사용"
                ),
            })
            connection = connection_factory()
            try:
                with connection:
                    _save_extraction(connection, original, replacement_article_id=replacement["id"], same_issue_id=same)
                    if not replacement.get("searchedReplacement"):
                        _save_extraction(connection, replacement, replaces_article_id=original["id"], same_issue_id=same)
            finally:
                connection.close()
            continue
        failure = {
            "articleId": original["id"], "title": original.get("title"),
            "source": original.get("source"), "url": original.get("url"),
            "priority": original.get("priority"), "failedStage": (original.get("attempts") or [{}])[-1].get("stage", "eligibility"),
            "reason": original.get("failureReason") or "no_equivalent_article",
            "replacementCandidates": searched_summaries,
            "availableActions": ["대체 기사 선택", "기사 선택 해제", "원문 직접 등록"],
            "rawCharacterCount": original.get("rawCharacterCount", 0),
            "cleanedCharacterCount": original.get("cleanedCharacterCount", 0),
        }
        excluded.append(failure)
        if original.get("priority") == "required":
            required_failures.append(failure)
    if required_failures:
        raise GenerationError(
            "REQUIRED_ARTICLE_EVIDENCE_MISSING",
            f"필수 보고 기사 {len(required_failures)}건의 본문 근거를 확보하지 못했습니다.",
            required_failures,
        )
    if not included:
        raise GenerationError("NO_ELIGIBLE_ARTICLES", "분석 적격 기사가 0건입니다.", excluded)

    budget.apply_article_limits(included, config)
    empty_required = [
        item for item in included
        if not item.get("includedText") and item.get("priority") == "required"
    ]
    if empty_required:
        raise GenerationError(
            "DOCUMENT_BUDGET_EXCEEDED",
            "필수 보고 기사의 완결 문장을 문서 예산 안에 포함할 수 없습니다.",
            [{"articleId": item["id"], "reason": "empty_after_article_budget"} for item in empty_required],
        )
    for article in [item for item in included if not item.get("includedText")]:
        included.remove(article)
        excluded.append({
            "articleId": article["id"],
            "priority": article.get("priority"),
            "reason": "article_budget_no_complete_sentence",
            "rawCharacterCount": article.get("rawCharacterCount", 0),
            "cleanedCharacterCount": article.get("cleanedCharacterCount", 0),
        })

    signature = "0" * 64
    def render() -> str:
        return builder.build(
            report_date=report_date, prepared_by=prepared_by, signature=signature, config=config,
            selected_count=len(selected), articles=included, replacements=replacements,
            excluded=excluded, weather_context=weather,
        )
    content = _fit_document(render, included, excluded, config)
    if not included:
        raise GenerationError(
            "DOCUMENT_BUDGET_EXCEEDED",
            "문서 예산 축소 후 분석 근거로 남은 기사가 없습니다.",
            excluded,
        )
    included_ids = {item["id"] for item in included}
    replacements[:] = [
        item for item in replacements if item["replacementArticleId"] in included_ids
    ]
    signature = input_signature(_signature_payload(
        report_date=report_date, prepared_by=prepared_by, selected=selected,
        included=included, weather=weather, config=config,
    ))
    content = render()
    if len(content) > int(config["document_budget"]["max_characters"]):
        raise GenerationError(
            "DOCUMENT_BUDGET_EXCEEDED", "최종 서명 반영 후 문서 예산을 충족하지 못했습니다."
        )

    connection = connection_factory()
    try:
        if save:
            # 최종 snapshot 검증부터 manifest commit까지 다른 작업본 mutation이
            # 끼어들지 못하도록 단일 작성자 잠금을 잡는다.
            connection.execute("BEGIN IMMEDIATE")
        current_source = build_source_context(connection, report_date, config)
        if (
            current_source is None
            or int(current_source.briefing["revision"]) != start_revision
            or current_source.signature != start_source_signature
        ):
            raise GenerationError("INPUT_CHANGED", "MD 생성 중 입력 데이터가 변경됐습니다.")
        path = storage.target_path(report_date, validation=validation)
        file_hash = content_hash(content)
        if save:
            try:
                evidence = {
                    f"A{index:02d}": article["id"]
                    for index, article in enumerate(included, start=1)
                }
                markdown_repo.upsert(
                    connection,
                    briefing_id=briefing["id"],
                    source_signature=start_source_signature,
                    input_signature=signature,
                    evidence=evidence,
                    file_hash=file_hash,
                    md_path=str(path),
                )
                storage.atomic_write(path, content)
                connection.commit()
            except (OSError, sqlite3.Error) as exc:
                connection.rollback()
                raise GenerationError("MD_STORAGE_FAILED", f"MD 저장 실패: {exc}") from exc
    finally:
        connection.close()
    article_results = []
    replacement_by_original = {item["originalArticleId"]: item["replacementArticleId"] for item in replacements}
    included_original_ids = {item.get("originalArticleId") or item["id"] for item in included}
    for article in prepared:
        replacement_id = replacement_by_original.get(article["id"])
        article_results.append({
            "articleId": article["id"],
            "status": "replaced" if replacement_id else article["status"],
            "replacementArticleId": replacement_id,
            "analysisEligible": article["id"] in included_original_ids,
        })
    result = {
        "ok": True, "mdPath": str(path), "inputSignature": signature,
        "fileHash": file_hash, "selectedCount": len(selected), "eligibleCount": len(included),
        "replacementCount": len(replacements), "excludedCount": len(excluded),
        "requiredFailures": [], "documentCharacters": len(content),
        "budgetStatus": "warning" if len(content) >= int(config["document_budget"]["warning_characters"]) else "ok",
        "articles": article_results, "excludedArticles": excluded,
        "publisherQuality": publisher_stats,
    }
    return GenerationOutput(content, result)
