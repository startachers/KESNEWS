from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from backend.app.repositories import briefing_repository as briefing_repo
from backend.app.repositories import weather_repository as weather_repo
from backend.app.services.analysis_markdown.signature import input_signature
from backend.app.services.reports.report_draft import ExchangeContext, build_exchange_context
from backend.app.services.weather.ai_context import build_weather_ai_context


@dataclass(frozen=True)
class SourceContext:
    briefing: dict[str, Any]
    exchange: ExchangeContext
    weather: dict[str, Any] | None
    signature: str


def weather_context(connection: sqlite3.Connection, briefing_id: str | None) -> dict[str, Any] | None:
    if not briefing_id:
        return None
    attachment = weather_repo.get_attachment(connection, briefing_id)
    if (
        attachment is None
        or not attachment["include_in_report"]
        or attachment["review_status"] != "reviewed"
    ):
        return None
    context, _, _ = build_weather_ai_context(
        weather_repo.snapshot_for_briefing(connection, briefing_id)
    )
    return context


def build_source_context(
    connection: sqlite3.Connection, report_date: str, config: dict[str, Any]
) -> SourceContext | None:
    briefing_row = briefing_repo.get_by_date(connection, report_date)
    if briefing_row is None:
        return None
    briefing = dict(briefing_row)
    exchange = build_exchange_context(connection, report_date)
    weather = weather_context(connection, briefing["id"])
    signature = input_signature(
        {
            "exchangeSignature": exchange.signature,
            "preparedBy": briefing.get("prepared_by") or "",
            "selectedUrlsAndPublishers": [
                {
                    "id": article["id"],
                    "url": article.get("url") or "",
                    "publisherId": article.get("publisherId"),
                    "publisherAllowed": article.get("publisherAllowed"),
                }
                for article in exchange.articles
            ],
            "weather": weather,
            "config": config,
        }
    )
    return SourceContext(briefing, exchange, weather, signature)
