from __future__ import annotations

import csv
import io
import sqlite3
from typing import Any

from backend.app.repositories import article_repository as article_repo
from backend.app.repositories import briefing_repository as briefing_repo
from backend.app.services.classification.service import CLASSIFIER_VERSION, classify_article, get_relevance
from backend.app.services.normalization.dates import since_bound_iso

RISK_LABELS = {"critical": "긴급", "watch": "주의", "routine": "일상"}
SENTIMENT_LABELS = {"positive": "긍정", "neutral": "중립", "negative": "부정"}
_REVERSE_RISK_LABELS = {label: value for value, label in RISK_LABELS.items()}
_REVERSE_SENTIMENT_LABELS = {label: value for value, label in SENTIMENT_LABELS.items()}

HEADERS = [
    "브리핑선정",
    "중요",
    "위험도",
    "정서",
    "분류",
    "관련도",
    "관련도점수",
    "관련도근거",
    "제목",
    "매체",
    "보도일시",
    "URL",
    "키워드",
    "메모",
    "주분류",
    "검색일치항목",
    "사고유형",
    "사고상태",
    "원인상태",
    "원인확정수준",
    "원인분야",
    "사망",
    "부상",
    "재산피해",
    "정전세대",
    "정전시간",
    "중요시설",
    "계획정전",
]

_FORMULA_PREFIXES = ("=", "+", "-", "@")


def _escape_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    if text and text[0] in _FORMULA_PREFIXES:
        return f"'{text}"
    return text


def _unescape_cell(value: str) -> str:
    if len(value) >= 2 and value[0] == "'" and value[1] in _FORMULA_PREFIXES:
        return value[1:]
    return value


def build_csv(connection: sqlite3.Connection, report_date: str) -> str:
    articles = article_repo.list_candidates(connection, report_date, include_dismissed=True)
    return build_csv_from_articles(articles)


def build_csv_from_articles(articles: list[dict[str, Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    writer.writerow(HEADERS)
    for article in articles:
        relevance = get_relevance({"title": article["title"], "description": article["description"]})
        incident = article.get("incident") or {}
        writer.writerow(
            [
                _escape_cell("Y" if article["included"] else "N"),
                _escape_cell("Y" if article["starred"] else "N"),
                _escape_cell(RISK_LABELS.get(article["risk"], article["risk"] or "")),
                _escape_cell(SENTIMENT_LABELS.get(article["sentiment"], article["sentiment"] or "")),
                _escape_cell(article["category"] or ""),
                _escape_cell(relevance["label"]),
                _escape_cell(relevance["score"]),
                _escape_cell("|".join(relevance["reasons"])),
                _escape_cell(article["title"]),
                _escape_cell(article["source"] or ""),
                _escape_cell(article["pubDate"] or ""),
                _escape_cell(article["url"]),
                _escape_cell("|".join(article["matchedKeywords"] or [])),
                _escape_cell(article["note"] or ""),
                _escape_cell(article.get("category") or ""),
                _escape_cell("|".join(article.get("matchedQueryIds") or [])),
                _escape_cell(incident.get("incident_type")),
                _escape_cell(incident.get("incident_status")),
                _escape_cell(incident.get("cause_status")),
                _escape_cell(incident.get("cause_certainty")),
                _escape_cell(incident.get("cause_domain")),
                _escape_cell(incident.get("deaths")),
                _escape_cell(incident.get("injuries")),
                _escape_cell(incident.get("property_damage_krw")),
                _escape_cell(incident.get("households")),
                _escape_cell(incident.get("duration_minutes")),
                _escape_cell(incident.get("critical_facility")),
                _escape_cell(
                    "Y" if incident.get("planned") is True else "N" if incident.get("planned") is False else ""
                ),
            ]
        )
    return "﻿" + buffer.getvalue()


def parse_csv(text: str) -> list[dict[str, str]]:
    cleaned = text.lstrip("﻿")
    reader = csv.reader(io.StringIO(cleaned))
    rows = list(reader)
    if not rows:
        return []
    header = rows[0]
    return [dict(zip(header, [_unescape_cell(cell) for cell in row])) for row in rows[1:]]


def import_csv(connection: sqlite3.Connection, report_date: str, rows: list[dict[str, str]]) -> dict[str, Any]:
    briefing = briefing_repo.get_by_date(connection, report_date)
    if briefing is None:
        raise briefing_repo.BriefingNotFound()

    imported = 0
    for index, row in enumerate(rows):
        title = row.get("제목") or "제목 없음"
        source = row.get("매체") or ""
        url = row.get("URL") or ""
        pub_date = row.get("보도일시") or None
        category = row.get("분류") or None
        primary_category = row.get("주분류") or category
        risk = _REVERSE_RISK_LABELS.get(row.get("위험도", ""))
        sentiment = _REVERSE_SENTIMENT_LABELS.get(row.get("정서", ""))
        keywords = [k for k in (row.get("키워드") or "").split("|") if k]
        note = row.get("메모") or None
        selected = (row.get("브리핑선정") or "").strip().upper() == "Y"
        starred = (row.get("중요") or "").strip().upper() == "Y"
        matched_query_ids = [item for item in (row.get("검색일치항목") or "").split("|") if item]
        incident_type = row.get("사고유형") or None
        incident = None
        if incident_type:
            def optional_int(field: str) -> int | None:
                value = (row.get(field) or "").replace(",", "").strip()
                return int(value) if value else None

            planned_value = (row.get("계획정전") or "").strip().upper()
            incident = {
                "incident_type": incident_type,
                "incident_status": row.get("사고상태") or None,
                "critical_facility": row.get("중요시설") or None,
            }
            if incident_type == "fire":
                incident.update(
                    {
                        "cause_status": row.get("원인상태") or None,
                        "cause_certainty": row.get("원인확정수준") or None,
                        "cause_domain": row.get("원인분야") or None,
                        "deaths": optional_int("사망"),
                        "injuries": optional_int("부상"),
                        "property_damage_krw": optional_int("재산피해"),
                    }
                )
            elif incident_type == "outage":
                incident.update(
                    {
                        "households": optional_int("정전세대"),
                        "duration_minutes": optional_int("정전시간"),
                        "planned": True if planned_value == "Y" else False if planned_value == "N" else None,
                    }
                )

        since = since_bound_iso(pub_date, 24 * 365)
        match = article_repo.find_matching_article(
            connection, url=url, title=title, published_at=pub_date, since_iso=since
        )
        if match is not None:
            article_id = match["id"]
        else:
            article_id = article_repo.create_article(
                connection,
                url=url,
                title=title,
                source=source,
                published_at=pub_date,
                description="",
                category_hint=category,
                manual=True,
            )
            article_repo.insert_observation(
                connection,
                article_id=article_id,
                collection_run_provider_id=None,
                provider="import-csv",
                provider_item_key=None,
                query_group_id=None,
                raw_url=url,
                raw_title=title,
                raw_source=source,
                raw_published_at=pub_date,
                raw_description="",
                raw_payload_json=None,
                dedup_method="new",
                dedup_score=None,
            )

        for query_id in matched_query_ids:
            article_repo.insert_observation(
                connection,
                article_id=article_id,
                collection_run_provider_id=None,
                provider="import-csv",
                provider_item_key=None,
                query_group_id=query_id,
                raw_url=url,
                raw_title=title,
                raw_source=source,
                raw_published_at=pub_date,
                raw_description="",
                raw_payload_json=None,
                dedup_method="imported_observation",
                dedup_score=None,
            )

        classified = classify_article(
            {"title": title, "description": "", "category": category}
        )
        imported_priority = {"critical": "required", "watch": "review", "routine": "reference"}.get(risk)
        classified["assessment"]["autoReasons"]["matchedTerms"] = list(
            dict.fromkeys([*classified["assessment"]["autoReasons"]["matchedTerms"], *keywords])
        )
        article_repo.upsert_assessment(
            connection,
            article_id=article_id,
            assessment={
                **classified["assessment"],
                "autoCategory": primary_category or classified["assessment"]["autoCategory"],
                "autoTone": sentiment or classified["assessment"]["autoTone"],
                "incident": incident,
            },
            classifier_version=CLASSIFIER_VERSION,
        )
        final_patch = {
            "finalCategory": category,
            "finalPriority": imported_priority,
            "finalTone": sentiment,
        }
        if any(value is not None for value in final_patch.values()):
            article_repo.patch_final_assessment(connection, article_id, final_patch)
        briefing_repo.set_article_state(
            connection,
            briefing["id"],
            article_id,
            selected=selected,
            starred=starred,
            note=note,
            dismissed=False,
            sort_order=index,
        )
        imported += 1

    return {"reportDate": report_date, "articlesImported": imported}
