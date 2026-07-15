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
    buffer = io.StringIO()
    writer = csv.writer(buffer, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    writer.writerow(HEADERS)
    for article in articles:
        relevance = get_relevance({"title": article["title"], "description": article["description"]})
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
        risk = _REVERSE_RISK_LABELS.get(row.get("위험도", ""))
        sentiment = _REVERSE_SENTIMENT_LABELS.get(row.get("정서", ""))
        keywords = [k for k in (row.get("키워드") or "").split("|") if k]
        note = row.get("메모") or None
        selected = (row.get("브리핑선정") or "").strip().upper() == "Y"
        starred = (row.get("중요") or "").strip().upper() == "Y"

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
                "autoCategory": category or classified["assessment"]["autoCategory"],
                "autoTone": sentiment or classified["assessment"]["autoTone"],
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
